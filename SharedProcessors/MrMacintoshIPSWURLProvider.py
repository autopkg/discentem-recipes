#!/usr/local/autopkg/python
"""See docstring for MrMacintoshIPSWURLProvider class"""

import re

from autopkglib import ProcessorError, URLGetter

__all__ = ["MrMacintoshIPSWURLProvider"]

SOURCE_URL = (
    "https://mrmacintosh.com/apple-silicon-m1-full-macos-restore-ipsw-firmware-files-database/"
)

# Matches UniversalMac_VERSION_BUILD_Restore.ipsw embedded in a CDN URL
_FILENAME_RE = re.compile(
    r"UniversalMac_(?P<version>[\d.]+)_(?P<build>[A-Za-z0-9]+)_Restore\.ipsw"
)


class MrMacintoshIPSWURLProvider(URLGetter):
    """Returns the URL for an Apple Silicon IPSW from the MrMacintosh firmware database.

    Sections on the page are identified by the bold header inside each table, e.g.:
      'macOS Golden Gate BETA Download Links'
      'macOS Tahoe Public Download Links'
      'macOS Sequoia Public Download Links'

    Pass a case-insensitive substring via section_name to select one.
    """

    description = __doc__
    input_variables = {
        "source_url": {
            "required": False,
            "default": SOURCE_URL,
            "description": "URL of the MrMacintosh IPSW database page.",
        },
        "section_name": {
            "required": False,
            "default": "Golden Gate BETA",
            "description": (
                "Case-insensitive substring matched against section headers on the page. "
                "Examples: 'Golden Gate BETA' (default), 'Tahoe Public', 'Sequoia Public', "
                "'Sonoma Final', 'Tahoe BETA'."
            ),
        },
        "macos_version": {
            "required": False,
            "default": "",
            "description": (
                "Exact macOS version to match within the section (e.g. '27.0'). "
                "Leave empty to return the latest (first) entry in the section."
            ),
        },
    }
    output_variables = {
        "url": {"description": "Direct CDN URL to the matched IPSW file."},
        "version": {"description": "macOS version string parsed from the IPSW filename (e.g. '27.0')."},
        "build": {"description": "macOS build string parsed from the IPSW filename (e.g. '26A5368g')."},
        "beta_version": {"description": "Beta label from the page's version column (e.g. 'Beta 2'). Empty string for release builds."},
        "release_date": {"description": "Release date from the page (e.g. '6/22'). Empty string if not listed."},
    }

    def _strip_tags(self, html):
        return re.sub(r"<[^>]+>", "", html).strip()

    def _parse_sections(self, html):
        """Return list of (header_text, [entry, ...]) for every table on the page.

        Each entry is a dict with keys: url, beta_version, release_date.
        """
        sections = []
        for chunk in re.split(r"(?=<table\b)", html):
            header_m = re.search(r"<strong>([^<]+)</strong>", chunk)
            if not header_m:
                continue
            entries = []
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.DOTALL):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
                if len(cells) < 2:
                    continue
                url_m = re.search(r'href="(https?://[^"]+\.ipsw)"', cells[0])
                if not url_m:
                    continue
                entries.append({
                    "url": url_m.group(1),
                    "beta_version": self._strip_tags(cells[1]),
                    "release_date": self._strip_tags(cells[2]) if len(cells) > 2 else "",
                })
            if entries:
                sections.append((header_m.group(1).strip(), entries))
        return sections

    def main(self):
        source_url = self.env.get("source_url", SOURCE_URL)
        section_filter = self.env.get("section_name", "Golden Gate BETA").lower()
        version_filter = self.env.get("macos_version", "").strip()

        self.output(f"Fetching IPSW database from {source_url}")
        html_bytes = self.download(source_url)
        html = html_bytes.decode("utf-8")

        sections = self._parse_sections(html)
        if not sections:
            raise ProcessorError("No IPSW table sections found on the page.")

        matched = next(
            ((h, entries) for h, entries in sections if section_filter in h.lower()),
            None,
        )
        if matched is None:
            available = ", ".join(f"'{h}'" for h, _ in sections)
            raise ProcessorError(
                f"No section matching '{section_filter}' found. "
                f"Available sections: {available}"
            )

        header, entries = matched
        self.output(f"Using section: {header} ({len(entries)} entries)")

        if version_filter:
            candidates = [e for e in entries if f"_{version_filter}_" in e["url"]]
            if not candidates:
                raise ProcessorError(
                    f"No IPSW found for version '{version_filter}' in section '{header}'."
                )
            entry = candidates[0]
        else:
            entry = entries[0]

        m = _FILENAME_RE.search(entry["url"])
        if not m:
            raise ProcessorError(
                f"Could not parse version/build from IPSW URL: {entry['url']}"
            )

        self.env["url"] = entry["url"]
        self.env["version"] = m.group("version")
        self.env["build"] = m.group("build")
        self.env["beta_version"] = entry["beta_version"]
        self.env["release_date"] = entry["release_date"]
        self.output(
            f"Found IPSW: {entry['url']}\n"
            f"  macOS version : {self.env['version']}\n"
            f"  Build         : {self.env['build']}\n"
            f"  Beta version  : {self.env['beta_version']}\n"
            f"  Release date  : {self.env['release_date']}"
        )


if __name__ == "__main__":
    PROCESSOR = MrMacintoshIPSWURLProvider()
    PROCESSOR.execute_shell()
