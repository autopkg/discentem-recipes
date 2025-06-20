# Downloaded from https://github.com/grahampugh/plist-yaml-plist/blob/7756b7d8a5a699542e6d4fb034c595dd67ff4dcc/plistyamlplist_lib/plist_yaml.py
# Commit: 7756b7d8a5a699542e6d4fb034c595dd67ff4dcc
# Downloaded at: 2025-04-12 23:26:15 UTC

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""If this script is run directly, it takes an input file and an output file
from the command line. The input file must be in PLIST format. The output file
will be in YAML format:

plist_yaml.py <input-file> <output-file>

The output file can be omitted. In this case, the name of the output file is
taken from the input file, with .yaml added to the end.
"""

import subprocess
import sys

from collections import OrderedDict

try:
    from plistlib import load as load_plist  # Python 3
except ImportError:
    from plistlib import Data  # Python 2
    from plistlib import readPlist as load_plist

try:
    from ruamel.yaml import dump
    from ruamel.yaml import add_representer
    from ruamel.yaml.nodes import MappingNode
except ImportError:
    subprocess.check_call([sys.executable, "-m", "ensurepip"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
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
    from ruamel.yaml import dump
    from ruamel.yaml import add_representer
    from ruamel.yaml.nodes import MappingNode

from . import handle_autopkg_recipes


def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return MappingNode("tag:yaml.org,2002:map", value)


def normalize_types(input_data):
    """This allows YAML and JSON to store Data fields as strings while preserving order."""
    if sys.version_info.major == 3 and isinstance(input_data, bytes):
        return input_data
    if sys.version_info.major == 2 and isinstance(input_data, Data):
        return input_data.data
    if isinstance(input_data, list):
        return [normalize_types(child) for child in input_data]
    if isinstance(input_data, dict):
        retval = OrderedDict()
        for key in input_data:
            retval[key] = normalize_types(input_data[key])
        return retval
    return input_data

def convert(xml):
    """Do the conversion."""
    add_representer(OrderedDict, represent_ordereddict)
    return dump(xml, width=float("inf"), default_flow_style=False)


def plist_yaml(in_path, out_path):
    """Convert plist to yaml."""
    with open(in_path, "rb") as in_file:
        input_data = load_plist(in_file)

    output = plist_yaml_from_dict(input_data)

    out_file = open(out_path, "w")
    out_file.writelines(output)
    print("Wrote to : {}\n".format(out_path))

def plist_yaml_from_dict(input_data: dict):
    """Convert plist to yaml from string."""
    normalized = normalize_types(input_data)

    # handle conversion of AutoPkg recipes
    if sys.version_info.major == 3 and input_data.get("name", "").endswith((".recipe", ".recipe.plist")):
        normalized = handle_autopkg_recipes.optimise_autopkg_recipes(normalized)
        output = convert(normalized)
        output = handle_autopkg_recipes.format_autopkg_recipes(output)
    else:
        output = convert(normalized)

    return output


def main():
    """Get the command line inputs if running this script directly."""
    if len(sys.argv) < 2:
        print("Usage: plist_yaml.py <input-file> <output-file>")
        sys.exit(1)

    in_path = sys.argv[1]

    try:
        sys.argv[2]
    except Exception:
        out_path = "%s.yaml" % in_path
    else:
        out_path = sys.argv[2]

    plist_yaml(in_path, out_path)


if __name__ == "__main__":
    main()
