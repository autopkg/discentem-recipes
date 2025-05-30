# Downloaded from https://github.com/grahampugh/plist-yaml-plist/blob/7756b7d8a5a699542e6d4fb034c595dd67ff4dcc/plistyamlplist_lib/yaml_plist.py
# Commit: 7756b7d8a5a699542e6d4fb034c595dd67ff4dcc
# Downloaded at: 2025-04-12 23:26:15 UTC

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""If this script is run directly, it takes an input file and an output file
from the command lineThe input file must be in YAML format. The output file
will be in PLIST format:

yaml_plist.py <input-file> <output-file>

The output file can be omitted, so long as the input file ends with .yaml.
In this case, the name of the output file is
taken from the input file, with .yaml removed from the end.
For best results, the input file should therefore be named with
"""

import subprocess
import sys
import os.path

try:  # python 3
    from plistlib import dumps as write_plist
except ImportError:  # python 2
    from plistlib import writePlistToString as write_plist

try:
    from ruamel import yaml
except ImportError:
    subprocess.check_call([sys.executable, "-m", "ensurepip", "--user"])
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-U",
            "pip",
            "setuptools",
            "wheel",
            "ruamel.yaml<0.18.0",
            "--user",
        ]
    )
    from ruamel import yaml


def convert(data):
    """Do the conversion."""
    lines = write_plist(data).decode("utf-8").splitlines()
    lines.append("")
    return "\n".join(lines)


def yaml_plist(in_path, out_path):
    """Convert yaml to plist."""
    try:
        in_file = open(in_path, "r")
    except IOError:
        print("ERROR: could not find " + in_path + "\n")
        return
    try:
        out_file = open(out_path, "w")
    except IOError:
        print("ERROR: could not create " + out_path + "\n")
        return

    input_data = yaml.safe_load(in_file)
    output = convert(input_data)

    out_file.writelines(output)
    print("Written to " + out_path + "\n")


def main():
    """Get the command line inputs if running this script directly."""
    if len(sys.argv) < 2:
        print("Usage: yaml_plist.py <input-file> <output-file>")
        sys.exit(1)

    in_path = sys.argv[1]
    try:
        sys.argv[2]
    except Exception:
        if in_path.endswith(".yaml"):
            filename, _ = os.path.splitext(in_path)
            out_path = filename
        else:
            print("Usage: yaml_plist.py <input-file> <output-file>")
            sys.exit(1)
    else:
        out_path = sys.argv[2]

    yaml_plist(in_path, out_path)


if __name__ == "__main__":
    main()
