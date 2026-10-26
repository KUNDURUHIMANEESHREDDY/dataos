#!/usr/bin/env python3
"""Validate workflow YAML and reject duplicate mapping keys before release checks run."""

from pathlib import Path
import sys

import yaml
from yaml.constructor import ConstructorError


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys instead of silently overriding them."""


def construct_unique_mapping(loader: UniqueKeyLoader, node, deep: bool = False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def main() -> int:
    workflow_dir = Path(".github/workflows")
    files = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
    if not files:
        print(f"ERROR: no workflow YAML files found in {workflow_dir}", file=sys.stderr)
        return 1

    failed = False
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as stream:
                yaml.load(stream, Loader=UniqueKeyLoader)
        except (OSError, yaml.YAMLError) as exc:
            print(f"FAIL: {path}: {exc}", file=sys.stderr)
            failed = True
        else:
            print(f"PASS: {path}: valid YAML with unique mapping keys")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
