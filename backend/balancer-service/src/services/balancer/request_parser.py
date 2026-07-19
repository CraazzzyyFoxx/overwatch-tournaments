from __future__ import annotations

import asyncio
import json
from json import JSONDecodeError

from pydantic import ValidationError

from src.services.balancer.config.public_contract import normalize_persisted_config_payload


def _parse_json_bytes(content: bytes) -> dict:
    return json.loads(content.decode("utf-8"))


class BalancerRequestParser:
    async def parse_player_data(self, uploaded_file) -> dict:
        if not uploaded_file:
            raise ValueError("'player_data_file' parameter must be provided")

        content = await uploaded_file.read()
        try:
            # Uploads can reach 25MB; decode + parse off the event loop.
            return await asyncio.to_thread(_parse_json_bytes, content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in uploaded file: {exc}") from exc

    def parse_config_overrides(self, raw_config: str | None) -> dict | None:
        if not raw_config:
            return None

        try:
            payload = json.loads(raw_config)
        except JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in 'config_overrides' field: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("'config_overrides' field must contain a JSON object")

        if "config_overrides" in payload:
            raise ValueError("'config_overrides' field must not contain a nested config_overrides object")

        try:
            validated = normalize_persisted_config_payload(payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid config overrides: {exc.errors()}") from exc

        return validated
