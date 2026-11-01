"""A player's game identity on the wire: the owner provider and the handle as stored; and the name a game surface shows."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from shared.core.social import PROVIDERS, display_social_handle

__all__ = ("PersonDisplayRead", "PlayerIdentityRead")


class PlayerIdentityRead(BaseModel):
    """``provider`` is a ``SocialProvider`` value; ``handle`` is the display form (``display_social_handle``)."""

    model_config = ConfigDict(frozen=True)

    provider: str
    handle: str

    @classmethod
    def of(cls, provider: str | None, handle: str | None) -> PlayerIdentityRead | None:
        """The identity ``handle`` denotes for ``provider``, or ``None`` when either is missing or blank."""
        if not provider:
            return None
        text = display_social_handle(provider, handle)
        return cls(provider=provider, handle=text) if text else None


def _split_tag(text: str) -> tuple[str, str | None]:
    """``Name#1234`` -> ``("Name", "#1234")`` at the LAST ``#``; mirrors the frontend ``splitHandle``."""
    index = text.rfind("#")
    if index <= 0:
        return text, None
    return text[:index], text[index:]


class PersonDisplayRead(BaseModel):
    """How a person is named on a surface owned by one game (docs/users-identity.md §3.6).

    ``name`` + ``tag`` is the first of: the person's VERIFIED game handle, the workspace's ``display_name``, an
    unverified game handle, the event's snapshot, the canonical ``players.user.name``. The game handle is the game's
    identity provider's account visible in scope (Steam: the persona name). ``canonical`` builds the profile link
    (``None``: nobody to link to); ``snapshot`` is set only when it names the person differently from what is shown.
    """

    # Every field is always serialized: the frontend type has no optional keys.
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    name: str
    tag: str | None = None
    canonical: str | None = None
    snapshot: str | None = None

    @classmethod
    def build(
        cls,
        *,
        canonical: str | None,
        provider: str | None = None,
        handle: str | None = None,
        handle_verified: bool = False,
        workspace_name: str | None = None,
        snapshot: str | None = None,
    ) -> PersonDisplayRead:
        """``handle`` is the game handle as shown and ``handle_verified`` its account's ``is_verified``
        (``game_handle`` / ``pick_game_handle``), already visibility-checked."""
        workspace_name, handle, snapshot = (
            (value or "").strip() or None for value in (workspace_name, handle, snapshot)
        )
        # A proven account names its owner over anything an organizer typed; an unproven one only fills in for it.
        shows_handle = handle is not None and (handle_verified or workspace_name is None)
        text = (handle if shows_handle else None) or workspace_name or snapshot or canonical or ""
        spec = PROVIDERS.get(provider or "")
        # A Steam persona is free text: a '#' in it is part of the name, not a discriminator.
        persona = shows_handle and spec is not None and spec.normalize == "steam_id"
        name, tag = (text, None) if persona else _split_tag(text)
        shown_snapshot = snapshot if snapshot is not None and snapshot.casefold() != text.casefold() else None
        return cls(name=name, tag=tag, canonical=canonical, snapshot=shown_snapshot)
