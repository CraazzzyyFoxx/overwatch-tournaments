"""One notification row -> the Discord message that carries it. No session.

Pure text assembly, kept out of the delivery service so the wording of eleven
kinds in two languages can be pinned by a test that needs neither a database
nor a broker.

Three rules the templates all obey:

* **Times are Discord timestamps**, ``<t:UNIX:F> (<t:UNIX:R>)``: Discord renders
  them in the *reader's* timezone, which is the only way a DM to a player in
  another country states the right hour without the platform storing one.
* **User text is escaped where Discord renders markdown.** Team and tournament
  names, a responder's name and a rejection reason are typed by people; an
  unescaped ``*`` italicises the rest of the description. Embed titles render
  no markdown, so they get the text verbatim. Pings are already off at the bot
  (``allow_mentions=False``), so this is about legibility, not safety.
* **A body line whose field is absent is dropped**, not rendered with a hole:
  ``closes_at`` is optional and ``model_dump(exclude_none=True)`` leaves it out
  of the snapshot entirely.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.services.notifications import NOTIFICATION_KINDS

__all__ = ("DiscordMessage", "TEMPLATES", "deep_link_path", "render_discord")

#: Teal, the same accent the balancer's lineup embeds post with.
_COLOR = 0x14B8A6

#: Payload keys whose value is an ISO timestamp rather than plain text.
_DATE_KEYS = frozenset({"closes_at", "scheduled_at"})

#: Discord's inline-markdown specials. ``>`` only starts a quote at the head of
#: a line, but a team name is interpolated into the head of one often enough.
_MARKDOWN = re.compile(r"([\\*_~`|>])")


@dataclass(frozen=True, slots=True)
class DiscordMessage:
    """What the bot is asked to send: plain text and/or one embed.

    ``content`` is ``None`` for every template today -- the embed carries the
    title, the detail line and the link -- but the field is part of the shape
    because ``DiscordCommandEvent`` accepts both and the delivery service
    forwards whatever is here.
    """

    content: str | None
    embed: dict[str, Any]


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def _timestamp(value: str) -> str:
    """``<t:UNIX:F> (<t:UNIX:R>)`` for an ISO string out of a payload snapshot.

    A snapshot written by ``model_dump(mode="json")`` carries the offset, but a
    producer that stamped a naive datetime would otherwise be read in the
    *worker's* local zone -- so a missing offset is read as UTC, the zone every
    other timestamp in the platform is stored in.
    """
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    unix = int(moment.timestamp())
    return f"<t:{unix}:F> (<t:{unix}:R>)"


# ``answer`` is a Literal in the payload schema, so the third branch is only
# reached by a row written before a future value existed.
_ANSWER_WORDS: dict[str, dict[str, str]] = {
    "ru": {"accepted": "принял", "declined": "отклонил"},
    "en": {"accepted": "accepted", "declined": "declined"},
}
_ANSWER_FALLBACK = {"ru": "ответил на", "en": "answered"}

#: ``kind -> (title template, body template)`` per locale. Every kind in
#: ``NOTIFICATION_KINDS`` except ``announcement.published`` (operator text that
#: already carries its own copy, and never leaves the app in v1) appears in
#: both locales -- the parity test is what keeps that true.
TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "ru": {
        "team_invite.received": ("{team_name} приглашает вас в состав на {tournament_name}", "Слот: {slot_code}"),
        "team_invite.answered": ("{responder_name} {answer_word} приглашение в команду {team_name}", ""),
        "registration.approved": ("Ваша заявка на {tournament_name} одобрена", ""),
        "registration.rejected": ("Ваша заявка на {tournament_name} отклонена", ""),
        "encounter.report_disputed": ("Отчёт по карте {position} вашего матча оспорен", ""),
        "team.kicked": ("Вас исключили из команды {team_name} ({tournament_name})", ""),
        "team.rejected": ("Команда {team_name} отклонена на {tournament_name}", "{reason}"),
        "team.disbanded": ("Команда {team_name} распущена ({tournament_name})", ""),
        "registration.opened": ("Регистрация на {tournament_name} открыта", "Закрытие: {closes_at}"),
        "check_in.opened": ("Чек-ин на {tournament_name} открыт", "Закрытие: {closes_at}"),
        "encounter.scheduled": (
            "Матч назначен: {home_team_name} — {away_team_name}",
            "{tournament_name}\nНачало: {scheduled_at}",
        ),
    },
    "en": {
        "team_invite.received": ("{team_name} invited you to their roster for {tournament_name}", "Slot: {slot_code}"),
        "team_invite.answered": ("{responder_name} {answer_word} your invite to {team_name}", ""),
        "registration.approved": ("Your registration for {tournament_name} was approved", ""),
        "registration.rejected": ("Your registration for {tournament_name} was rejected", ""),
        "encounter.report_disputed": ("The report for map {position} of your match is disputed", ""),
        "team.kicked": ("You were removed from {team_name} ({tournament_name})", ""),
        "team.rejected": ("Team {team_name} was rejected from {tournament_name}", "{reason}"),
        "team.disbanded": ("{team_name} was disbanded ({tournament_name})", ""),
        "registration.opened": ("Registration for {tournament_name} is open", "Closes: {closes_at}"),
        "check_in.opened": ("Check-in for {tournament_name} is open", "Closes: {closes_at}"),
        "encounter.scheduled": (
            "Match scheduled: {home_team_name} vs {away_team_name}",
            "{tournament_name}\nStarts: {scheduled_at}",
        ),
    },
}

#: The kinds a Discord message exists for at all.
DELIVERABLE_KINDS: frozenset[str] = frozenset(NOTIFICATION_KINDS) - {"announcement.published"}

_PARTICIPANTS_KINDS = frozenset(
    {
        "team_invite.received",
        "registration.approved",
        "registration.rejected",
        "team.kicked",
        "team.rejected",
        "team.disbanded",
    }
)
_PREGAME_KINDS = frozenset({"encounter.report_disputed", "encounter.scheduled"})
_TOURNAMENT_KINDS = frozenset({"registration.opened", "check_in.opened"})


def deep_link_path(kind: str, payload: Mapping[str, Any]) -> str | None:
    """Where the message points, or ``None`` when the kind has no destination.

    ``ponytail:`` these paths are duplicated by hand from
    ``frontend/src/lib/notifications/href.ts`` -- the inbox and the DM must land
    on the same screen, and there is no shared route manifest to read them
    from. Upgrade path is that manifest, when a third consumer appears.
    """
    tournament_id = payload.get("tournament_id")
    if not isinstance(tournament_id, int):
        return None
    if kind in _PARTICIPANTS_KINDS:
        return f"/tournaments/{tournament_id}/participants"
    if kind in _PREGAME_KINDS:
        encounter_id = payload.get("encounter_id")
        return f"/tournaments/{tournament_id}/pregame/{encounter_id}" if isinstance(encounter_id, int) else None
    if kind in _TOURNAMENT_KINDS:
        return f"/tournaments/{tournament_id}"
    # team_invite.answered carries a pre-formation team id and no tournament.
    return None


def _fields(kind: str, payload: Mapping[str, Any], locale: str, *, escape: bool) -> dict[str, str]:
    """The payload as interpolation-ready strings: rendered times, and user text
    escaped when it lands where Discord renders markdown."""
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            if key in _DATE_KEYS:
                fields[key] = _timestamp(value)
            else:
                fields[key] = _escape(value) if escape else value
        else:
            fields[key] = str(value)
    if kind == "team_invite.answered":
        answer = str(payload.get("answer", ""))
        fields["answer_word"] = _ANSWER_WORDS[locale].get(answer, _ANSWER_FALLBACK[locale])
    return fields


def render_discord(kind: str, payload: Mapping[str, Any], *, locale: str, site_url: str) -> DiscordMessage:
    """The embed for one notification, in ``locale``.

    An unknown locale falls back to ``ru`` (the platform default) rather than
    failing a delivery over a settings value; an unknown *kind* raises, because
    silently posting nothing would hide a missing template forever.
    """
    templates = TEMPLATES.get(locale) or TEMPLATES["ru"]
    template = templates.get(kind)
    if template is None:
        raise ValueError(f"no Discord template for notification kind {kind!r}")

    title_template, body_template = template
    field_locale = locale if locale in TEMPLATES else "ru"
    try:
        body = body_template.format(**_fields(kind, payload, field_locale, escape=True)).strip()
    except KeyError:
        # The snapshot does not carry that field (an absent ``closes_at``):
        # the detail line is dropped, the headline still stands on its own.
        body = ""

    # Embed titles render no markdown, so an escape there would show as a
    # literal backslash; Discord also refuses a title over 256 characters.
    title = title_template.format(**_fields(kind, payload, field_locale, escape=False))
    embed: dict[str, Any] = {"title": title[:256], "color": _COLOR}
    if body:
        embed["description"] = body
    path = deep_link_path(kind, payload)
    if path is not None:
        embed["url"] = f"{site_url.rstrip('/')}{path}"
    return DiscordMessage(content=None, embed=embed)
