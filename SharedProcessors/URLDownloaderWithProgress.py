#!/usr/local/autopkg/python
"""See docstring for URLDownloaderWithProgress class"""

import subprocess

from autopkglib import ProcessorError
from autopkglib.URLDownloader import URLDownloader

__all__ = ["URLDownloaderWithProgress"]


class URLDownloaderWithProgress(URLDownloader):
    """Wraps URLDownloader and shows a curl progress bar during downloads.

    Replaces curl's --silent flag with --progress-bar and lets stderr pass
    through to the terminal so the progress bar is visible. All other
    URLDownloader behaviour (ETag caching, filename prefetch, etc.) is unchanged.
    """

    description = __doc__

    def prepare_base_curl_cmd(self):
        cmd = super().prepare_base_curl_cmd()
        # --silent suppresses the progress bar; swap it out.
        cmd = [arg for arg in cmd if arg != "--silent"]
        cmd.append("--progress-bar")
        return cmd

    def execute_curl(self, curl_cmd, text=True):
        """Run curl with stdout captured (for header parsing) and stderr inherited
        from the parent process so the progress bar renders in the terminal."""
        errors = "ignore" if text else None
        try:
            result = subprocess.run(
                curl_cmd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=None,  # inherit — lets --progress-bar render
                check=True,
                text=text,
                errors=errors,
            )
        except subprocess.CalledProcessError as e:
            stderr = self._curl_stderr_text(e.stderr)
            self.output(f"ERROR: {stderr.removeprefix('curl: ')}")
            raise ProcessorError(stderr) from e
        # stderr is not captured; return empty string to satisfy the parent's
        # (stdout, stderr, returncode) contract. check=True means returncode is 0.
        return result.stdout, "", result.returncode


if __name__ == "__main__":
    PROCESSOR = URLDownloaderWithProgress()
    PROCESSOR.execute_shell()
