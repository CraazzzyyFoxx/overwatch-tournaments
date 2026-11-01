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

    ``name`` + ``tag`` is the first of: the workspace's ``display_name``, the person's game handle (the game's
    identity provider's primary account visible in scope; Steam: the persona name), the event's snapshot, the
    canonical ``players.user.name``. ``canonical`` builds the profile link (``None``: nobody to link to);
    ``snapshot`` is set only when it names the person differently from what is shown.
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
        workspace_name: str | None = None,
        snapshot: str | None = None,
    ) -> PersonDisplayRead:
        """``handle`` is the game handle as shown (``game_handle`` / ``pick_game_handle``), already visibility-checked."""
        workspace_name, handle, snapshot = (
            (value or "").strip() or None for value in (workspace_name, handle, snapshot)
        )
        spec = PROVIDERS.get(provider or "")
        # A Steam persona is free text: a '#' in it is part of the name, not a discriminator.
        persona = handle is not None and spec is not None and spec.normalize == "steam_id"
        text = workspace_name or handle or snapshot or canonical or ""
        name, tag = (text, None) if persona and not workspace_name else _split_tag(text)
        shown_snapshot = snapshot if snapshot is not None and snapshot.casefold() != text.casefold() else None
        return cls(name=name, tag=tag, canonical=canonical, snapshot=shown_snapshot)
