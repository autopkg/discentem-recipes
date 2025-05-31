from __future__ import absolute_import

import os
import tempfile
import datetime
import sys
from io import BytesIO
import typing
from plistlib import dumps as plist_dumps

lib_path = os.path.join(os.path.dirname(__file__), "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from plist_yaml_plist.plist_yaml import plist_yaml_from_dict
from autopkglib import Processor, ProcessorError
from autopkglib.github import GitHubSession
from plistlib import loads as plist_loads

__all__ = ["AutopkgVendorer"]

class AutopkgVendorer(Processor):
    description = __doc__

    input_variables = {
        "github_repo": {"required": True, "description": "GitHub repository (owner/repo)"},
        "folder_path": {"required": True, "description": "Folder or file inside repo to download"},
        "commit_sha": {"required": True, "description": "Commit SHA to download from"},
        "destination_path": {"required": True, "description": "Directory to save files"},
        "github_token": {"required": False, "description": "GitHub token for auth/rate limit"},
        "comment_style": {"required": False, "description": "Force comment style: 'yaml' or 'xml'"},
        "convert_to_yaml": {"required": False, "description": "Convert plist/recipe to YAML (default True)"},
        "required_license": {"required": True, "description": "Required license type"},
    }

    output_variables = {
        "downloaded_folder_path": {"description": "Path to downloaded folder"},
        "autopkg_vendorer_summary_result": {
            "description": "Summary of the vendoring process",
            "required": False,
        },
    }

    def download_text_file(self, session, repo, path, commit_sha):
        raw_url = f"https://raw.githubusercontent.com/{repo}/{commit_sha}/{path}"
        temp_file = tempfile.mktemp()
        curl_cmd = ["/usr/bin/curl", "--location", "--silent", "--fail", "--output", temp_file, raw_url]

        try:
            session.download_with_curl(curl_cmd)
            with open(temp_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise ProcessorError(f"Failed to download {path} at {commit_sha}: {e}")

    def license_type(self, session, repo, commit_sha):
        endpoint = f"/repos/{repo}/license"
        query = f"ref={commit_sha}"
        response_json, status = session.call_api(endpoint, query=query)
        if status != 200:
            raise ProcessorError(f"GitHub API error while checking for LICENSE in root: {status}")
        return response_json["license"].get("spdx_id")

    def generate_comment_header(self, repo, path, commit_sha, style):
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        github_url = f"https://github.com/{repo}/blob/{commit_sha}/{path}"

        if style == "xml":
            return f"<!--\nDownloaded from {github_url}\nCommit: {commit_sha}\nDownloaded at: {timestamp}\n-->\n\n"
        elif style == "yaml":
            return f"# Downloaded from {github_url}\n# Commit: {commit_sha}\n# Downloaded at: {timestamp}\n\n"
        else:
            raise ProcessorError(f"Invalid comment style: {style}")

    def insert_comment(self, header, content, style):
        if style == "xml":
            lines = content.splitlines(keepends=True)
            if len(lines) >= 3:
                return ''.join(lines[:3]) + header + ''.join(lines[3:])
        return header + content

    def is_license_file(self, item_name):
        return item_name.lower() == "license"

    def process_file(self, session, repo, item_path, item_name, commit_sha, dest_path, convert_to_yaml):
        file_contents = self.download_text_file(session, repo, item_path, commit_sha)

        if item_name.endswith(('.recipe')):
            plist_data = plist_loads(file_contents.encode("utf-8"))
            plist_data = dict(plist_data)  # convert to plain dict to avoid internal dict issues

            if convert_to_yaml:
                header = self.generate_comment_header(repo, item_path, commit_sha, "yaml")
                modified_yaml = plist_yaml_from_dict(plist_data)
                full_contents = header + modified_yaml
                dest_path = dest_path.replace(".recipe", ".recipe.yaml")
            else:
                updated_plist_str = plist_dumps(plist_data).decode("utf-8")
                header = self.generate_comment_header(repo, item_path, commit_sha, "xml")
                full_contents = self.insert_comment(header, updated_plist_str, "xml")
        else:
            style = self.env.get("comment_style", "yaml")
            header = self.generate_comment_header(repo, item_path, commit_sha, style)
            full_contents = self.insert_comment(header, file_contents, style)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(full_contents)
        self.output(f"Downloaded: {item_path} → {dest_path}")

    def vendor_path(self, session, repo, path, commit_sha, dest_base, rel_base="", convert_to_yaml=False):
        endpoint = f"/repos/{repo}/contents/{path}"
        query = f"ref={commit_sha}"

        response_json, status = session.call_api(endpoint, query=query)
        if status != 200:
            raise ProcessorError(f"GitHub API error: {status} for path {path}")

        items = response_json if isinstance(response_json, list) else [response_json]

        vendorer_paths = []

        for item in items:
            item_type = item.get("type")
            item_path = item.get("path")
            item_name = item.get("name")
            rel_path = os.path.join(rel_base, item_name)
            dest_path = os.path.join(dest_base, rel_path)

            if item_type == "dir":
                self.vendor_path(session, repo, item_path, commit_sha, dest_base, rel_path, convert_to_yaml)
            elif item_type == "file":
                self.process_file(session, repo, item_path, item_name, commit_sha, dest_path, convert_to_yaml)
                vendorer_paths.append(dest_path)
            else:
                self.output(f"Skipping unknown type '{item_type}' at {item_path}")

        return vendorer_paths

    def main(self):
        repo = self.env["github_repo"]
        folder_path = self.env["folder_path"]
        commit_sha = self.env["commit_sha"]
        github_token = self.env.get("github_token")
        destination_path = self.env.get("destination_path") or tempfile.mkdtemp(prefix="github_folder_")
        convert_to_yaml = self.env.get("convert_to_yaml", True)
        required_license = self.env.get("required_license")

        os.makedirs(destination_path, exist_ok=True)
        gh_session = GitHubSession(github_token)

        found_license = self.license_type(gh_session, repo, commit_sha)
        if not found_license == required_license:
            raise ProcessorError(f"Input variable license_type ({required_license}) does not match the found license ({found_license}).")

        vendored_paths = self.vendor_path(
            session=gh_session,
            repo=repo,
            path=folder_path,
            commit_sha=commit_sha,
            dest_base=destination_path,
            convert_to_yaml=convert_to_yaml,
        )

        self.env["downloaded_folder_path"] = destination_path
        self.output(f"Downloaded folder available at: {destination_path}")

        self.env["autopkg_vendorer_summary_result"] = {
            "summary_text": "Files downloaded and vendored successfully.",
            "report_fields": ["Vendored Recipes"],
            "data": {
                "Vendored Recipes": "\n".join(vendored_paths),
            }
        }

if __name__ == "__main__":
    processor = AutopkgVendorer()
    processor.execute_shell()
