"""Export one service's OpenAPI schema fragment from its ``src/openapi_schemas``.

Run from a SERVICE directory (cwd must contain ``src/``); prints a JSON fragment
``{"schemas": {...}, "operations": {...}}`` to stdout. ``schemas`` are the flat
JSON-Schema ``$defs`` for every referenced Pydantic model (refs rewritten to
``#/components/schemas/{model}``); ``operations`` maps each RPC subject to its
request/response ref names.

Importing ``src.openapi_schemas`` transitively loads ``src.core.config`` which
instantiates ``Settings()`` — provide dummy POSTGRES_*/REDIS_URL/etc. env (the
script never connects). The wrapper ``export_openapi_schemas.sh`` does this.
"""

from __future__ import annotations

import json
import os
import re
import sys

# python <script> puts the script's dir on sys.path[0], not the cwd; the service
# package lives under the cwd, so make ``import src.*`` resolve.
sys.path.insert(0, os.getcwd())

from pydantic.json_schema import models_json_schema  # noqa: E402

from src.openapi_schemas import OPERATIONS  # type: ignore  # noqa: E402

# Component names are namespaced by service ("tournament.TournamentRead") so the
# merge across services never conflates two same-named, differently-shaped models
# (e.g. each service has its own DivisionGridTierRead). A service's models only
# reference same-service models, so blanket-prefixing every ref is correct.
PREFIX = os.path.basename(os.getcwd()).removesuffix("-service")
_REF = re.compile(r"#/components/schemas/")


def main() -> None:
    pairs: list[tuple[object, str]] = []
    seen: set[tuple[int, str]] = set()

    def add(model: object, mode: str) -> None:
        key = (id(model), mode)
        if key not in seen:
            seen.add(key)
            pairs.append((model, mode))

    for op in OPERATIONS.values():
        if op.response is not None:
            add(op.response, "serialization")
        if op.request is not None:
            add(op.request, "validation")

    keys_map, top = models_json_schema(pairs, ref_template="#/components/schemas/{model}")
    defs = top.get("$defs", {})

    # Namespace every schema name + every internal $ref with the service prefix.
    schemas = {
        f"{PREFIX}.{name}": json.loads(_REF.sub(f"#/components/schemas/{PREFIX}.", json.dumps(schema)))
        for name, schema in defs.items()
    }

    def ref_name(model: object, mode: str) -> str:
        return f"{PREFIX}." + keys_map[(model, mode)]["$ref"].rsplit("/", 1)[-1]

    operations: dict[str, dict] = {}
    for subject, op in OPERATIONS.items():
        entry: dict = {}
        if op.response is not None:
            entry["response"] = {"ref": ref_name(op.response, "serialization"), "array": op.response_array}
        if op.request is not None:
            entry["request"] = {"ref": ref_name(op.request, "validation"), "array": False}
        operations[subject] = entry

    json.dump({"schemas": schemas, "operations": operations}, sys.stdout, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
