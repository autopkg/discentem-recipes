#!/usr/bin/env python3
#
# Copyright (c) Facebook, Inc. and its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""See docstring for AcrolinxURLProvider class"""

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import os
from autopkglib import ProcessorError
from autopkglib.URLGetter import URLGetter



__all__ = ["AcrolinxURLProvider"]

URL = "https://{}:{}@download.acrolinx.com:1443/api/deliverables/{}/download/latest"


class AcrolinxURLProvider(URLGetter):
    """Provides a download URL for Acrolinx."""

    description = __doc__
    input_variables = {
        "acrolinx_uuid": {"required": True, "description": "UUID that seems to correspond to a specific Acrolinx customer portal"},
        "acrolinx_username": {"required": False, "description": "Username for authentication."},
        "acrolinx_password": {"required": False, "description": "Password for authentication"},
        "acrolinx_debug": {"required": False, "description": "Prints out debug env info"}
    }
    output_variables = {"url": {"description": "Download URL for Acrolinx."}}

    def main(self):
        """Find the download URL"""
        
        uuid = self.env.get("acrolinx_uuid", None)
        username = self.env.get("acrolinx_username", None)
        password = self.env.get("acrolinx_password", None)
        
        if uuid == "%acrolinx_uuid%" or uuid == None:
            if os.environ.get("acrolinx_uuid") is not None:
                uuid = os.environ["acrolinx_uuid"]
            else:
                raise ProcessorError(
                    "acrolinx_uuid was not provided, fallback to environment variable return None"
                )
        if username == "%acrolinx_username%" or username == None:
            if os.environ.get("acrolinx_username") is not None:
                username = os.environ["acrolinx_username"]
            else:
                raise ProcessorError(
                    "acrolinx_username was not provided, fallback to environment variable return None"
                )
        if password == "%acrolinx_password%" or password == None:
            if os.environ.get("acrolinx_password") is not None:
                password = os.environ["acrolinx_password"]
            else:
                raise ProcessorError(
                    "acrolinx_password was not provided, fallback to environment variable return None"
                )
        url = URL.format(username, password, uuid)
        cmd = [self.curl_binary(), "--write-out", "'%{json}'", url]
        out, err, code = self.execute_curl(cmd)
        if code != 0:
            raise ProcessorError(
                f"{cmd} exited non-zero.\n{err}"
            )
        try:
            # regex to match a url
            regex = r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)"
            match = re.search(regex, out)

            url = match[0]
            self.output(f"Found URL: {url}")
            self.env["url"] = url
        except:
            raise ProcessorError(
                f"download url not found in output:\n {out}"
            )
        


if __name__ == "__main__":
    PROCESSOR = AcrolinxURLProvider()
    PROCESSOR.execute_shell()
