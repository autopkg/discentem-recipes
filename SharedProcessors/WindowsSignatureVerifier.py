#!/usr/local/autopkg/python
#
# Copyright 2014 Hannes Juutilainen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""See docstring for WindowsSignatureVerifier class"""

# Borrowed with <3 from Nick McSpadden https://github.com/autopkg/autopkg/commit/6ac5792d935d2c09d7acde4c552ca9594509faea

import os.path
import subprocess
import re
import json

from glob import glob
from distutils.version import StrictVersion
from autopkglib import ProcessorError
from autopkglib.DmgMounter import DmgMounter
from autopkglib import is_windows

__all__ = ["WindowsSignatureVerifier"]



class WindowsSignatureVerifier(DmgMounter):
    """Verifies application bundle or installer package signature.
    Requires version 0.3.1."""

    input_variables = {
        "DISABLE_CODE_SIGNATURE_VERIFICATION": {
            "required": False,
            "description":
                ("Skip this Processor step altogether. Typically this "
                 "would be invoked using AutoPkg's defaults or via '--key' "
                 "CLI options at the time of the run, rather than being "
                 "defined explicitly within a recipe."),
        },
        "input_path": {
            "required": True,
            "description":
                ("File path to any codesigned file."),
        },
        "expected_subject": {
            "required": False,
            "description":
                ("The Subject of the Authenticode signature. Can be queried "
                 "with:\n"
                 "(Get-AuthenticodeSignature '<path>').SignerCertificate."
                 "Subject"),
        },
    }
    output_variables = {
    }

    description = __doc__

    def main(self):
        if not is_windows():
            self.output("Not on Windows, not running Windows Signature "
                        "Verifier")
            return
        if self.env.get('DISABLE_CODE_SIGNATURE_VERIFICATION'):
            self.output("Code signature verification disabled for this recipe "
                        "run.")
            return
        input_path = self.env['input_path']

        powershell = "C:\\windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        # Get authenticode information about the file
        cmd = [
            "Get-AuthenticodeSignature",
            input_path,
            "|",
            "ConvertTo-Json",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            executable=powershell
        )
        (out, err) = proc.communicate()
        data = json.loads(out)
        if data['SignerCertificate']['Subject'] != self.env['expected_subject']:
            raise ProcessorError(
                "Code signature mismatch! Expected %s but "
                "received %s" % (
                    self.env['expected_subject'],
                    data['SignerCertificate']['Subject']
                )
            )


if __name__ == '__main__':
    PROCESSOR = WindowsSignatureVerifier()
    PROCESSOR.execute_shell()