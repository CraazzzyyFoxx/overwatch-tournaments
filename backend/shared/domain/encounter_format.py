"""Which features an encounter's format admits.

Everything built on two sides -- series score, map veto, hero pick-ban, captain
series reports, Challonge -- accepts only a duel. The guard lives here, not per
feature, so the refusal carries one code the frontend localizes.
"""

from __future__ import annotations

from typing import Protocol

from shared.core import http_status as status
from shared.core.enums import EncounterFormat
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException

__all__ = ("ensure_format",)


class _HasFormat(Protocol):
    format: str


def ensure_format(encounter: _HasFormat, expected: EncounterFormat) -> None:
    # ``None`` is a just-constructed row whose column default ('duel') has not
    # been written yet -- the format only materializes on flush, and every duel
    # writer (persist, scrim, Challonge) builds an Encounter without naming it.
    actual = encounter.format or EncounterFormat.DUEL
    if actual != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[
                ApiExc(
                    code=f"encounter_not_{expected.value}",
                    msg=f"This action needs a {expected.value} encounter; this one is {actual}",
                )
            ],
        )
