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
        "destination_path": {"required": False, "description": "Directory to save files"},
        "github_token": {"required": False, "description": "GitHub token for auth/rate limit"},
        "comment_style": {"required": False, "description": "Force comment style: 'yaml' or 'xml'"},
        "convert_to_yaml": {"required": False, "description": "Convert plist/recipe to YAML (default True)"},
        "new_identifier": {"required": True, "description": "Override Identifier entirely"},
        "new_name": {"required": False, "description": "Override Name in the recipe, if present"},
        "fail_if_license_missing": {"required": False, "description": "Fail if LICENSE file not found"},
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

    def check_root_for_license(self, session, repo, commit_sha):
        endpoint = f"/repos/{repo}/contents"
        query = f"ref={commit_sha}"
        response_json, status = session.call_api(endpoint, query=query)
        if status != 200 or not isinstance(response_json, list):
            raise ProcessorError(f"GitHub API error while checking for LICENSE in root: {status}")
        return any(item.get("type") == "file" and item.get("name", "").lower() == "license" for item in response_json)

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

    def modify_identifier_and_name(self, plist_data, new_identifier=None, new_name=None):
        if "Identifier" not in plist_data:
            raise ProcessorError("No Identifier found in recipe.")
        if not new_identifier:
            raise ProcessorError("No new identifier provided.")
        plist_data["Identifier"] = new_identifier
        if new_name:
            plist_data["Name"] = new_name
        return plist_data

    def is_license_file(self, item_name):
        return item_name.lower() == "license"

    def process_file(self, session, repo, item_path, item_name, commit_sha, dest_path, convert_to_yaml, new_identifier, new_name) -> str:
        file_contents = self.download_text_file(session, repo, item_path, commit_sha)

        if item_name.endswith(('.recipe')):
            plist_data = plist_loads(file_contents.encode("utf-8"))
            plist_data = dict(plist_data)  # convert to plain dict to avoid internal dict issues
            plist_data = self.modify_identifier_and_name(plist_data, new_identifier, new_name)

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
        return dest_path

    def vendor_path(self, session, repo, path, commit_sha, dest_base, rel_base="", convert_to_yaml=False, new_identifier=None, new_name=None):
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
                self.vendor_path(session, repo, item_path, commit_sha, dest_base, rel_path, convert_to_yaml, new_identifier, new_name)
            elif item_type == "file":
                vendorer_paths.append(
                    self.process_file(session, repo, item_path, item_name, commit_sha, dest_path, convert_to_yaml, new_identifier, new_name)
                )
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
        new_identifier = self.env.get("new_identifier")
        new_name = self.env.get("new_name")

        os.makedirs(destination_path, exist_ok=True)
        gh_session = GitHubSession(github_token)

        license_found = self.check_root_for_license(gh_session, repo, commit_sha)
        if self.env.get("fail_if_license_missing") and not license_found:
            raise ProcessorError("LICENSE file not found in the root of the repository.")

        vendored_paths = self.vendor_path(
            session=gh_session,
            repo=repo,
            path=folder_path,
            commit_sha=commit_sha,
            dest_base=destination_path,
            convert_to_yaml=convert_to_yaml,
            new_identifier=new_identifier,
            new_name=new_name,
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
