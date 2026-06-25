"""Merge per-service OpenAPI schema fragments into the gateway manifest.

Reads the fragment JSON files given as args (output of
``export_openapi_schemas.py``) and prints the merged ``{schemas, operations}``.
Schema names are global; identical models across services produce identical
schemas, so a plain dict union is safe (a name clash with differing shapes would
be a modelling bug worth surfacing — we warn on stderr).
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    schemas: dict[str, object] = {}
    operations: dict[str, object] = {}
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as fh:
            frag = json.load(fh)
        for name, schema in frag.get("schemas", {}).items():
            if name in schemas and schemas[name] != schema:
                print(f"warning: schema name clash with differing shape: {name}", file=sys.stderr)
            schemas[name] = schema
        operations.update(frag.get("operations", {}))
    json.dump({"schemas": schemas, "operations": operations}, sys.stdout, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
