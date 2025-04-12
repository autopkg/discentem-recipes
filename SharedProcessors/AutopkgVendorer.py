from __future__ import absolute_import

import os
import tempfile
import json
import datetime

from autopkglib import Processor, ProcessorError
from autopkglib.github import GitHubSession

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

    def generate_comment_header(self, repo, path, commit_sha):
        """Generates a comment block to prepend to the file."""
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        github_url = f"https://github.com/{repo}/blob/{commit_sha}/{path}"

        # Use explicit override if provided
        override = self.env.get("comment_style")
        if override:
            style = override.lower()
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
            # Insert header as the 4th line, after the XML declaration, DOCTYPE, and <plist>
            if len(lines) >= 3:
                return ''.join(lines[:3]) + header + ''.join(lines[3:])
            
            return header + content  # fallback if fewer than 3 lines
        return header + content


    def download_folder_recursive(self, session, repo, path, commit_sha, dest_base, rel_base=""):
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
                self.download_folder_recursive(session, repo, item_path, commit_sha, dest_base, rel_path)
            elif item_type == "file":
                file_contents = self.download_text_file_at_commit_raw(session, repo, item_path, commit_sha)
                header = self.generate_comment_header(repo, item_path, commit_sha)
                full_contents = self.insert_comment_header(header, file_contents, self.env.get("comment_style", "xml"))

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

        destination_path = self.env.get("destination_path")
        if not destination_path:
            destination_path = tempfile.mkdtemp(prefix="github_folder_")
        else:
            os.makedirs(destination_path, exist_ok=True)

        # Setup GitHub session
        gh_session = GitHubSession(github_token)

        try:
            self.download_folder_recursive(
                session=gh_session,
                repo=repo,
                path=folder_path,
                commit_sha=commit_sha,
                dest_base=destination_path,
                rel_base=""
            )
        except Exception as e:
            raise ProcessorError(f"Failed to download folder from GitHub: {e}")

        self.env["downloaded_folder_path"] = destination_path
        self.output(f"All files downloaded to: {destination_path}")

if __name__ == "__main__":
    processor = AutopkgVendorer()
    processor.execute_shell()
