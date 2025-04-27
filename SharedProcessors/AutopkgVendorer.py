from __future__ import absolute_import

import os
import tempfile
import datetime
import sys
from io import BytesIO
import typing

lib_path = os.path.join(os.path.dirname(__file__), "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from plist_yaml_plist.plist_yaml import plist_yaml_from_dict

from autopkglib import Processor, ProcessorError
from autopkglib.github import GitHubSession
from plistlib import loads as plist_loads

__all__ = ["AutopkgVendorer"]

class AutopkgVendorer(Processor):
    """Downloads all text files in a specific folder (recursively) from a GitHub repo at a specific commit,
    and prepends a comment header with download metadata."""

    description = __doc__

    input_variables = {
        "github_repo": {
            "required": True,
            "description": "GitHub repository in the form 'owner/repo'",
        },
        "folder_path": {
            "required": True,
            "description": "Path to the folder inside the repo you want to download",
        },
        "commit_sha": {
            "required": True,
            "description": "Specific commit SHA to pin the download to",
        },
        "destination_path": {
            "required": False,
            "description": "Directory where files should be downloaded (defaults to a temp dir)",
        },
        "github_token": {
            "required": False,
            "description": "GitHub token for private repos or to increase rate limits",
        },
        "comment_style": {
            "required": False,
            "description": "Override comment style: 'yaml' or 'xml'. Default is based on file extension.",
        },
        "convert_to_yaml": {
            "required": False,
            "description": "Whether to convert plist or recipe files to YAML. Defaults to True.",
        },
        "identifier_prefix": {
            "required": True,
            "description": "Prefix to use for the Identifier in the vendored recipe.",
        },
    }

    output_variables = {
        "downloaded_folder_path": {
            "description": "Path to the downloaded folder",
        }
    }

    def download_text_file_at_commit_raw(self, session, repo, path, commit_sha):
        """Downloads a text file from a repo at a specific commit SHA."""
        raw_url = f"https://raw.githubusercontent.com/{repo}/{commit_sha}/{path}"

        temp_file_path = tempfile.mktemp()
        curl_cmd = [
            "/usr/bin/curl",
            "--location",
            "--silent",
            "--fail",
            "--output", temp_file_path,
            raw_url
        ]

        try:
            session.download_with_curl(curl_cmd)
            with open(temp_file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise ProcessorError(f"Failed to download {path} at {commit_sha}: {e}")

    def generate_comment_header(self, repo, path, commit_sha, comment_style=None):
        """Generates a comment block to prepend to the file."""
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        github_url = f"https://github.com/{repo}/blob/{commit_sha}/{path}"

        if comment_style:
            style = comment_style.lower()
        elif path.endswith((".recipe", ".xml")):
            style = "xml"
        else:
            style = "yaml"

        if style == "xml":
            return (
                f"<!--\n"
                f"Downloaded from {github_url}\n"
                f"Commit: {commit_sha}\n"
                f"Downloaded at: {timestamp}\n"
                f"-->\n\n"
            )
        elif style == "yaml":
            return (
                f"# Downloaded from {github_url}\n"
                f"# Commit: {commit_sha}\n"
                f"# Downloaded at: {timestamp}\n\n"
            )
        else:
            raise ProcessorError(f"Invalid comment_style: '{style}'. Must be 'yaml' or 'xml'.")

    def insert_comment_header(self, header: str, content: str, comment_style: str) -> str:
        if comment_style == "xml":
            lines = content.splitlines(keepends=True)
            if len(lines) >= 3:
                return ''.join(lines[:3]) + header + ''.join(lines[3:])
            return header + content
        return header + content

    def convert_to_yaml(self, content: str, fn_edit_in_place: typing.Callable = None) -> str:
        """Convert a string plist to YAML format."""
        try:
            plist_data = plist_loads(content.encode("utf-8"))
            if fn_edit_in_place:
                plist_data = fn_edit_in_place(plist_data)
            return plist_yaml_from_dict(plist_data)
        except Exception as e:
            raise ProcessorError(f"Failed to convert to YAML: {e}")

    def vendor_recipe_content(self, session, repo, path, commit_sha, dest_base, identifier_prefix, rel_base="", convert_to_yaml=False):
        endpoint = f"/repos/{repo}/contents/{path}"
        query = f"ref={commit_sha}"

        response_json, status = session.call_api(endpoint, query=query)
        if status != 200 or not isinstance(response_json, list):
            raise ProcessorError(f"GitHub API error: status {status} for path '{path}'")

        for item in response_json:
            item_type = item.get("type")
            item_path = item.get("path")
            item_name = item.get("name")
            rel_path = os.path.join(rel_base, item_name)
            dest_path = os.path.join(dest_base, rel_path)

            if item_type == "dir":
                self.download_folder_recursive(session, repo, item_path, commit_sha, dest_base, rel_path, convert_to_yaml)
            elif item_type == "file":
                file_contents = self.download_text_file_at_commit_raw(session, repo, item_path, commit_sha)

                if item_name.endswith((".plist", ".recipe")) and convert_to_yaml:
                    header = self.generate_comment_header(repo, item_path, commit_sha, comment_style="yaml")
                    def change_recipe_identifier(plist_data):
                        # Change the identifier to match the new path
                        if isinstance(plist_data, dict):
                            pdata = plist_data.copy()
                            if "Identifier" not in plist_data:
                                raise ProcessorError(f"No Identifier found in {path}")
                            original_identifier = plist_data["Identifier"]
                            pdata["Identifier"] = f"{identifier_prefix}.{original_identifier}"
                        return pdata
                    yaml_body = self.convert_to_yaml(
                        file_contents,
                        fn_edit_in_place=change_recipe_identifier
                        )
                    full_contents = header + yaml_body
                    comment_style = "yaml"
                    dest_path = dest_path.replace(".recipe", ".recipe.yaml")
                else:
                    comment_style = "xml"
                    header = self.generate_comment_header(repo, item_path, commit_sha, comment_style)
                    full_contents = self.insert_comment_header(header, file_contents, comment_style)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(full_contents)

                self.output(f"Downloaded: {item_path} → {dest_path}")
            else:
                self.output(f"Skipping unknown type '{item_type}' at {item_path}")

    def main(self):
        repo = self.env["github_repo"]
        folder_path = self.env["folder_path"]
        commit_sha = self.env["commit_sha"]
        github_token = self.env.get("github_token")
        convert_to_yaml = self.env.get("convert_to_yaml", True)
        identifier_prefix = self.env.get("identifier_prefix", None)
        if not identifier_prefix:
            raise ProcessorError("identifier_prefix is required")

        destination_path = self.env.get("destination_path")
        if not destination_path:
            destination_path = tempfile.mkdtemp(prefix="github_folder_")
        else:
            os.makedirs(destination_path, exist_ok=True)

        gh_session = GitHubSession(github_token)

        try:
            self.vendor_recipe_content(
                session=gh_session,
                repo=repo,
                path=folder_path,
                commit_sha=commit_sha,
                dest_base=destination_path,
                rel_base="",
                convert_to_yaml=convert_to_yaml,
                identifier_prefix=identifier_prefix,
            )
        except Exception as e:
            raise ProcessorError(f"Failed to download folder from GitHub: {e}")

        self.env["downloaded_folder_path"] = destination_path
        self.output(f"All files downloaded to: {destination_path}")


if __name__ == "__main__":
    processor = AutopkgVendorer()
    processor.execute_shell()
