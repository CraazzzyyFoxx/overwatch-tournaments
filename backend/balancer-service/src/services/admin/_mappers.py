from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm.attributes import NO_VALUE

from src import models
from src.schemas.admin import balancer as admin_schemas
from src.services.balancer.config.provider import serialize_saved_config_payload
from src.services.balancer.config.public_contract import normalize_balance_response_payload


def loaded_relationship_or_none(instance: object, attribute: str):
    loaded_value = sa.inspect(instance).attrs[attribute].loaded_value
    if loaded_value is NO_VALUE:
        return None
    return loaded_value


def serialize_balance(
    balance: models.BalancerBalance,
    *,
    already_normalized: bool = False,
) -> admin_schemas.BalanceRead:
    """Map a ``BalancerBalance`` row to its read schema.

    ``already_normalized=True`` skips the config/result normalization passes:
    ``save_balance`` stores exactly ``serialize_saved_config_payload`` /
    ``normalize_balance_response_payload`` output, so re-running them on the
    just-saved multi-MB result is pure waste. Reads from the DB (which may
    hold older-format rows) keep the default normalizing path.
    """
    return admin_schemas.BalanceRead(
        id=balance.id,
        tournament_id=balance.tournament_id,
        config_json=balance.config_json if already_normalized else serialize_saved_config_payload(balance.config_json),
        result_json=(
            balance.result_json if already_normalized else normalize_balance_response_payload(balance.result_json)
        ),
        saved_by=balance.saved_by,
        saved_at=balance.saved_at,
        exported_at=balance.exported_at,
        export_status=balance.export_status,
    )


def serialize_tournament_config(
    tournament_config: models.BalancerTournamentConfig,
) -> admin_schemas.BalancerTournamentConfigRead:
    return admin_schemas.BalancerTournamentConfigRead(
        id=tournament_config.id,
        tournament_id=tournament_config.tournament_id,
        workspace_id=tournament_config.workspace_id,
        config_json=serialize_saved_config_payload(tournament_config.config_json),
        updated_by=tournament_config.updated_by,
        updated_at=tournament_config.updated_at,
    )
