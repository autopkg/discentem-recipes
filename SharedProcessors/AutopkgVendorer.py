from __future__ import absolute_import

import json
import os
import subprocess
import sys
import tempfile
import typing
from datetime import datetime, timezone
from collections import OrderedDict
import enum
from plistlib import dumps as plist_dumps

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from lib.plist_yaml_plist.plist_yaml import plist_yaml_from_dict
from autopkglib import Processor, ProcessorError
from autopkglib.github import GitHubSession
from plistlib import loads as plist_loads

__all__ = ["AutopkgVendorer"]

class AutopkgVendorer(Processor):
    description = __doc__

    input_variables = {
        "github_repo": {"required": True, "description": "GitHub repository (owner/repo)"},
        "assets": {"required": True, "description": "Folder path or list of file paths inside the repo to download"},
        "commit_sha": {"required": True, "description": "Commit SHA to download from"},
        "destination_path": {"required": True, "description": "Directory to save files"},
        "github_token": {"required": False, "description": "GitHub token for auth/rate limit"},
        "comment_style": {"required": False, "description": "Force comment style: 'yaml' or 'xml'"},
        "convert_to_yaml": {"required": False, "description": "Convert plist/recipe to YAML (default True)"},
        "required_license": {"required": False, "description": "Required license type"},
        "opinionated_ordering": {
            "required": False,
            "description": "Use opinionated ordering for recipe keys (default True)",
        },
    }

    output_variables = {
        "downloaded_folder_path": {"description": "Path to downloaded folder"},
        "autopkg_vendorer_summary_result": {
            "description": "Summary of the vendoring process",
            "required": False,
        },
    }
    def move_keys_to_top(self, d: dict, first_keys: list[str]) -> OrderedDict:
        """Reorder dictionary `d` so that keys in `first_keys` appear first, in that order."""
        od = OrderedDict()
        for key in first_keys:
            if key in d:
                od[key] = d[key]
        for key, value in d.items():
            if key not in od:
                od[key] = value
        return od

    def head_request(self, session, url: str) -> None:
        temp_fd, temp_file = tempfile.mkstemp()
        os.close(temp_fd)
        curl_cmd = ["/usr/bin/curl", "--head", "--location", "--silent", "--fail", "--output", temp_file, url]
        try:
            session.download_with_curl(curl_cmd)
        except Exception as e:
            raise ProcessorError(f"HEAD request failed for {url}: {e}")
        finally:
            os.unlink(temp_file)

    def download_text_file(self, session, repo: str, path: str, commit_sha: str) -> str:
        raw_url = f"https://raw.githubusercontent.com/{repo}/{commit_sha}/{path}"
        temp_fd, temp_file = tempfile.mkstemp()
        os.close(temp_fd)
        curl_cmd = ["/usr/bin/curl", "--location", "--silent", "--fail", "--output", temp_file, raw_url]
        try:
            self.head_request(session, raw_url)
            session.download_with_curl(curl_cmd)
            with open(temp_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise ProcessorError(f"Failed to download {path} at {commit_sha}: {e}")
        finally:
            os.unlink(temp_file)

    def _check_license_api(self, session, repo: str, commit_sha: str) -> typing.Optional[str]:
        endpoint = f"/repos/{repo}/license"
        query = f"ref={commit_sha}"
        response_json, status = session.call_api(endpoint, query=query)
        if status != 200:
            raise ProcessorError(f"GitHub API error {status} checking license for {repo}")
        return response_json["license"].get("spdx_id")

    def _detect_spdx_id(self, content: str) -> typing.Optional[str]:
        c = content.lower()
        if "apache license" in c and "version 2.0" in c:
            return "Apache-2.0"
        if "mit license" in c or "permission is hereby granted, free of charge" in c:
            return "MIT"
        if "gnu general public license" in c:
            if "version 3" in c:
                return "GPL-3.0-only"
            if "version 2" in c:
                return "GPL-2.0-only"
        if "gnu lesser general public license" in c:
            if "version 3" in c:
                return "LGPL-3.0-only"
            if "version 2.1" in c:
                return "LGPL-2.1-only"
        if "mozilla public license" in c and "version 2.0" in c:
            return "MPL-2.0"
        if "isc license" in c or ("permission to use, copy, modify" in c and "isc" in c):
            return "ISC"
        if "redistributions of source code must retain" in c:
            if "neither the name" in c:
                return "BSD-3-Clause"
            return "BSD-2-Clause"
        return None

    def _check_license_curl(self, session, repo: str, commit_sha: str) -> typing.Optional[str]:
        candidates = ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "license.md", "license.txt"]
        for candidate in candidates:
            try:
                content = self.download_text_file(session, repo, candidate, commit_sha)
                return self._detect_spdx_id(content)
            except ProcessorError:
                continue
        raise ProcessorError(f"No license file found in {repo} at {commit_sha}")

    def license_type(self, session, repo: str, commit_sha: str, github_token: typing.Optional[str] = None) -> typing.Optional[str]:
        if github_token:
            return self._check_license_api(session, repo, commit_sha)
        return self._check_license_curl(session, repo, commit_sha)

    class CommentStyle(enum.Enum):
        YAML = "yaml"
        XML = "xml"

    def generate_comment_header(self, repo, path, commit_sha, style: CommentStyle) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        github_url = f"https://github.com/{repo}/blob/{commit_sha}/{path}"

        if isinstance(style, str):
            try:
                style = self.CommentStyle(style.lower())
            except ValueError as e:
                raise ProcessorError("Invalid comment style. Expected one of: yaml, xml") from e

        if style == self.CommentStyle.XML:
            return f"<!--\nDownloaded from {github_url}\nCommit: {commit_sha}\nDownloaded at: {timestamp}\n-->\n\n"
        elif style == self.CommentStyle.YAML:
            return f"# Downloaded from {github_url}\n# Commit: {commit_sha}\n# Downloaded at: {timestamp}\n\n"
        else:
            raise ProcessorError(f"Invalid comment style: {style}")

    def insert_comment(self, header, content, style: CommentStyle) -> str:
        if style == self.CommentStyle.XML:
            lines = content.splitlines(keepends=True)
            if len(lines) >= 3:
                return ''.join(lines[:3]) + header + ''.join(lines[3:])
        return header + content

    def is_license_file(self, item_name):
        return item_name.lower() == "license"

    def process_file(self, session, repo, item_path: str, item_name: str, commit_sha: str, dest_path: str, convert_to_yaml: bool = False, opinionated_ordering: bool = True):
        file_contents = self.download_text_file(session, repo, item_path, commit_sha)
        self.output(f"Downloaded: {item_path} → {dest_path}")

        if item_name.endswith(('.recipe')):
            plist_data = plist_loads(file_contents.encode("utf-8"))
            plist_data = dict(plist_data)

            if opinionated_ordering:
                for step_index, step in enumerate(plist_data.get('Process', [])):
                    reordered_step = self.move_keys_to_top(step, ['Processor', 'Arguments'])
                    plist_data['Process'][step_index] = reordered_step

                self.output(f"Reordered recipe: {item_path}")

            if convert_to_yaml:
                header = self.generate_comment_header(repo, item_path, commit_sha, self.CommentStyle.YAML)
                modified_yaml = plist_yaml_from_dict(plist_data)
                full_contents = header + modified_yaml
                dest_path = dest_path.replace(".recipe", ".recipe.yaml")
            else:
                updated_plist_str = plist_dumps(plist_data, sort_keys=False).decode("utf-8")
                header = self.generate_comment_header(repo, item_path, commit_sha, self.CommentStyle.XML)
                full_contents = self.insert_comment(header, updated_plist_str, self.CommentStyle.XML)
        else:
            style = self.env.get("comment_style", "yaml")
            header = self.generate_comment_header(repo, item_path, commit_sha, style)
            full_contents = self.insert_comment(header, file_contents, style)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(full_contents)

    def _list_directory_api(self, session, repo: str, path: str, commit_sha: str) -> list:
        endpoint = f"/repos/{repo}/contents/{path}"
        query = f"ref={commit_sha}"
        response_json, status = session.call_api(endpoint, query=query)
        if status != 200:
            raise ProcessorError(f"GitHub API error: {status} for path {path}")
        return response_json if isinstance(response_json, list) else [response_json]

    def _list_directory_curl(self, session, repo: str, path: str, commit_sha: str) -> list:
        tarball_url = f"https://github.com/{repo}/archive/{commit_sha}.tar.gz"
        temp_fd, temp_file = tempfile.mkstemp(suffix=".tar.gz")
        os.close(temp_fd)
        curl_cmd = ["/usr/bin/curl", "--location", "--silent", "--fail", "--output", temp_file, tarball_url]
        try:
            session.download_with_curl(curl_cmd)
        except Exception as e:
            raise ProcessorError(f"Failed to download tarball for {repo} at {commit_sha}: {e}")

        try:
            result = subprocess.run(["tar", "-tz", "-f", temp_file], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise ProcessorError(f"Failed to list tarball contents: {e.stderr}")
        finally:
            os.unlink(temp_file)

        lines = result.stdout.splitlines()
        if not lines:
            raise ProcessorError(f"Empty tarball for {repo} at {commit_sha}")

        top_level = lines[0].rstrip("/").split("/")[0]
        prefix = f"{top_level}/{path}/"

        items = []
        seen_dirs = set()
        for line in lines:
            if line.endswith("/"):
                continue  # skip explicit directory entries; subdirs are discovered via their file children
            line = line.rstrip("/")
            if not line.startswith(prefix):
                continue
            rel = line[len(prefix):]
            if not rel:
                continue
            parts = rel.split("/")
            if len(parts) == 1:
                item_name = parts[0]
                items.append({"type": "file", "path": f"{path}/{item_name}", "name": item_name})
            elif parts[0] not in seen_dirs:
                dir_name = parts[0]
                seen_dirs.add(dir_name)
                items.append({"type": "dir", "path": f"{path}/{dir_name}", "name": dir_name})

        return items

    def _list_directory(self, session, repo: str, path: str, commit_sha: str, github_token: typing.Optional[str] = None) -> list:
        if github_token:
            return self._list_directory_api(session, repo, path, commit_sha)
        return self._list_directory_curl(session, repo, path, commit_sha)

    def vendor_path(self, session, repo: str, path: str, commit_sha: str, dest_base, rel_base="", convert_to_yaml=False, opinionated_ordering=True, github_token=None):
        path = path.rstrip("/")
        raw_url = f"https://raw.githubusercontent.com/{repo}/{commit_sha}/{path}"

        try:
            self.head_request(session, raw_url)
            item_name = os.path.basename(path)
            rel_path = os.path.join(rel_base, item_name) if rel_base else item_name
            dest_path = os.path.join(dest_base, rel_path)
            self.process_file(session, repo, path, item_name, commit_sha, dest_path, convert_to_yaml, opinionated_ordering=opinionated_ordering)
            return [dest_path]
        except ProcessorError:
            pass

        # Path is a directory
        items = self._list_directory(session, repo, path, commit_sha, github_token=github_token)
        if not items:
            raise ProcessorError(f"Path not found as file or directory: {path} in {repo} at {commit_sha}")
        vendored_paths = []

        for item in items:
            item_type = item.get("type")
            item_path = item.get("path")
            item_name = item.get("name")
            rel_path = os.path.join(rel_base, item_name)
            dest_path = os.path.join(dest_base, rel_path)

            if item_type == "dir":
                vendored_paths.extend(self.vendor_path(session, repo, item_path, commit_sha, dest_base, rel_path, convert_to_yaml, opinionated_ordering=opinionated_ordering, github_token=github_token))
            elif item_type == "file":
                self.process_file(session, repo, item_path, item_name, commit_sha, dest_path, convert_to_yaml, opinionated_ordering=opinionated_ordering)
                vendored_paths.append(dest_path)
            else:
                self.output(f"Skipping unknown type '{item_type}' at {item_path}")

        return vendored_paths

    def main(self):
        repo = self.env["github_repo"]
        assets = self.env["assets"]
        commit_sha = self.env["commit_sha"]
        github_token = self.env.get("github_token")
        destination_path = self.env["destination_path"]
        convert_to_yaml = self.env.get("convert_to_yaml", True)
        required_license = self.env.get("required_license", None)
        opinionated_ordering = self.env.get("opinionated_ordering", True)

        os.makedirs(destination_path, exist_ok=True)
        gh_session = GitHubSession(github_token)

        if required_license:
            found_license = self.license_type(gh_session, repo, commit_sha, github_token=github_token)
            if not found_license == required_license:
                raise ProcessorError(f"Input variable required_license ({required_license}) does not match the found license ({found_license}).")

        paths = assets if isinstance(assets, list) else [assets]
        vendored_paths = []
        for path in paths:
            vendored_paths.extend(self.vendor_path(
                session=gh_session,
                repo=repo,
                path=path,
                commit_sha=commit_sha,
                dest_base=destination_path,
                convert_to_yaml=convert_to_yaml,
                opinionated_ordering=opinionated_ordering,
                github_token=github_token,
            ))

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