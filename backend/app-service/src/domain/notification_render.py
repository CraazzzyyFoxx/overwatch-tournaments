"""One notification row -> the Discord card that carries it. No session.

Pure text assembly, kept out of the delivery service so the wording of eleven
kinds in two languages can be pinned by a test that needs neither a database
nor a broker. The bot owns the layout (``discord-service``
``src/interactions/cards.py``); this module decides what the card says, its
colour, its picture and its buttons -- links, and the one-click actions the
bot answers itself (``src/interactions/actions.py``).

Rules every card obeys:

* **Times are Discord timestamps**, ``<t:UNIX:F> (<t:UNIX:R>)``: Discord renders
  them in the *reader's* timezone, which is the only way a DM to a player in
  another country states the right hour without the platform storing one.
* **Every interpolated value is escaped.** A Components V2 card is markdown end
  to end, and team, tournament and workspace names and a rejection reason are
  typed by people: ``[claim](https://evil.example)`` would otherwise be a
  clickable link inside the platform's own DM, ``# name`` a headline and
  ``<@id>`` a mention. Pings are off at the bot as well (``allow_mentions=False``).
* **User text is clipped before it is escaped**, so no name or reason, however
  long, pushes a card past Discord's 4000-character limit (a 400 there parks
  the command in the DLQ instead of sending it).
* **A detail line whose field is absent is dropped**, not rendered with a hole:
  ``closes_at`` is optional and ``model_dump(exclude_none=True)`` leaves it out
  of the snapshot entirely; an empty ``reason`` means none was given.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard, DiscordLinkButton
from shared.services.notifications import NOTIFICATION_KINDS

__all__ = ("DELIVERABLE_KINDS", "TEMPLATES", "deep_link_path", "render_discord")

# The inbox's status palette (``NotificationList.getKindConfig``), so the DM
# reads the same as the bell: green is good news, red is bad, amber wants
# action, blue is information, teal is the platform accent.
_GREEN = 0x10B981
_RED = 0xF43F5E
_AMBER = 0xF59E0B
_BLUE = 0x3B82F6
_TEAL = 0x14B8A6

_COLORS: dict[str, int] = {
    "team_invite.received": _BLUE,
    "team_invite.answered": _BLUE,
    "registration.approved": _GREEN,
    "registration.rejected": _RED,
    "encounter.report_disputed": _AMBER,
    "team.kicked": _RED,
    "team.rejected": _RED,
    "team.disbanded": _RED,
    "registration.opened": _TEAL,
    "check_in.opened": _AMBER,
    "encounter.scheduled": _BLUE,
}
_ANSWER_COLORS = {"accepted": _GREEN, "declined": _RED}

#: Payload keys whose value is an ISO timestamp rather than plain text.
_DATE_KEYS = frozenset({"closes_at", "scheduled_at"})

#: Everything Discord markdown gives a meaning to. A backslash before ASCII
#: punctuation is always consumed, so over-escaping is invisible to the reader.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]<#-])")

#: A ``{field}`` in a template line.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

#: Per-value caps. Three names and a reason stay far below the card limit even
#: after escaping doubles every character.
_NAME_LIMIT = 200
_REASON_LIMIT = 1000


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


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


# ``answer`` is a Literal in the payload schema, so the fallback is only
# reached by a row written before a future value existed.
_ANSWER_WORDS: dict[str, dict[str, str]] = {
    "ru": {"accepted": "принял", "declined": "отклонил"},
    "en": {"accepted": "accepted", "declined": "declined"},
}
_ANSWER_FALLBACK = {"ru": "ответил на", "en": "answered"}

#: Same words as the frontend's ``slotCodes``; a custom roster code shows as is.
_SLOT_LABELS: dict[str, dict[str, str]] = {
    "ru": {"tank": "Танк", "damage": "Дамаг", "support": "Саппорт", "flex": "Флекс"},
    "en": {"tank": "Tank", "damage": "Damage", "support": "Support", "flex": "Flex"},
}
_SUBSTITUTE = {"ru": " (замена)", "en": " (substitute)"}

#: ``kind -> (heading, sentence, detail lines)`` per locale. The heading is the
#: kind's label from the workspace admin screen; every kind in
#: ``NOTIFICATION_KINDS`` except ``announcement.published`` (operator text that
#: already carries its own copy, and never leaves the app in v1) appears in
#: both locales -- the parity test is what keeps that true.
TEMPLATES: dict[str, dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "ru": {
        "team_invite.received": (
            "Приглашение в команду",
            "**{team_name}** приглашает вас в состав на **{tournament_name}**.",
            ("**Слот:** {slot}",),
        ),
        "team_invite.answered": (
            "Ответ на приглашение",
            "**{responder_name}** {answer_word} приглашение в команду **{team_name}**.",
            (),
        ),
        "registration.approved": ("Заявка принята", "Ваша заявка на **{tournament_name}** одобрена.", ()),
        "registration.rejected": ("Заявка отклонена", "Ваша заявка на **{tournament_name}** отклонена.", ()),
        "encounter.report_disputed": ("Отчёт оспорен", "Отчёт по карте {position} вашего матча оспорен.", ()),
        "team.kicked": (
            "Исключение из команды",
            "Вас исключили из команды **{team_name}** на **{tournament_name}**.",
            (),
        ),
        "team.rejected": (
            "Команда отклонена",
            "Команда **{team_name}** отклонена на **{tournament_name}**.",
            ("**Причина:** {reason}",),
        ),
        "team.disbanded": ("Команда распущена", "Команда **{team_name}** на **{tournament_name}** распущена.", ()),
        "registration.opened": (
            "Регистрация открыта",
            "Открыта регистрация на **{tournament_name}**.",
            ("**Закрытие:** {closes_at}",),
        ),
        "check_in.opened": (
            "Чек-ин открыт",
            "Открыт чек-ин на **{tournament_name}** — подтвердите участие.",
            ("**Закрытие:** {closes_at}",),
        ),
        "encounter.scheduled": (
            "Матч назначен",
            "**{home_team_name}** — **{away_team_name}** на **{tournament_name}**.",
            ("**Начало:** {scheduled_at}",),
        ),
    },
    "en": {
        "team_invite.received": (
            "Team invite",
            "**{team_name}** invited you to their roster for **{tournament_name}**.",
            ("**Slot:** {slot}",),
        ),
        "team_invite.answered": (
            "Invite answered",
            "**{responder_name}** {answer_word} your invite to **{team_name}**.",
            (),
        ),
        "registration.approved": (
            "Registration approved",
            "Your registration for **{tournament_name}** was approved.",
            (),
        ),
        "registration.rejected": (
            "Registration rejected",
            "Your registration for **{tournament_name}** was rejected.",
            (),
        ),
        "encounter.report_disputed": (
            "Report disputed",
            "The report for map {position} of your match is disputed.",
            (),
        ),
        "team.kicked": ("Removed from team", "You were removed from **{team_name}** in **{tournament_name}**.", ()),
        "team.rejected": (
            "Team rejected",
            "Team **{team_name}** was rejected from **{tournament_name}**.",
            ("**Reason:** {reason}",),
        ),
        "team.disbanded": ("Team disbanded", "**{team_name}** in **{tournament_name}** was disbanded.", ()),
        "registration.opened": (
            "Registration opened",
            "Registration for **{tournament_name}** is open.",
            ("**Closes:** {closes_at}",),
        ),
        "check_in.opened": (
            "Check-in opened",
            "Check-in for **{tournament_name}** is open — confirm you are playing.",
            ("**Closes:** {closes_at}",),
        ),
        "encounter.scheduled": (
            "Match scheduled",
            "**{home_team_name}** vs **{away_team_name}** in **{tournament_name}**.",
            ("**Starts:** {scheduled_at}",),
        ),
    },
}

#: Link captions, one per destination.
_LINK_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "participants": "Перейти к участникам",
        "pregame": "Открыть матч",
        "tournament": "Открыть турнир",
    },
    "en": {
        "participants": "View participants",
        "pregame": "Open match",
        "tournament": "Open tournament",
    },
}

#: Captions of the buttons the bot answers itself (discord-service ``ACTIONS``).
_ACTION_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "invite.accept": "Принять",
        "invite.decline": "Отклонить",
        "check_in": "Пройти чек-ин",
        "registration.view": "Моя заявка",
    },
    "en": {
        "invite.accept": "Accept",
        "invite.decline": "Decline",
        "check_in": "Check in",
        "registration.view": "My registration",
    },
}

#: The DM's way out, deliberately small: it opens a reply only the reader sees,
#: and the switch-everything-off button lives there, not on the card.
_MENU_LABEL = "🔕"

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
    # team_invite.answered names a pre-formation team, which has no page.
    return None


def _destination(kind: str) -> str:
    if kind in _PARTICIPANTS_KINDS:
        return "participants"
    return "pregame" if kind in _PREGAME_KINDS else "tournament"


def _fields(kind: str, payload: Mapping[str, Any], locale: str) -> dict[str, str]:
    """The payload as interpolation-ready markdown: rendered times, and user
    text clipped and escaped."""
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            if key in _DATE_KEYS:
                fields[key] = _timestamp(value)
            else:
                fields[key] = _escape(_clip(value.strip(), _REASON_LIMIT if key == "reason" else _NAME_LIMIT))
        else:
            fields[key] = str(value)
    if kind == "team_invite.answered":
        answer = str(payload.get("answer", ""))
        fields["answer_word"] = _ANSWER_WORDS[locale].get(answer, _ANSWER_FALLBACK[locale])
    if kind == "team_invite.received" and "slot_code" in fields:
        slot = _SLOT_LABELS[locale].get(str(payload["slot_code"]), fields["slot_code"])
        fields["slot"] = slot + (_SUBSTITUTE[locale] if payload.get("is_substitute") is True else "")
    return fields


def _action_row(kind: str, payload: Mapping[str, Any], labels: Mapping[str, str]) -> list[DiscordButton]:
    """The one-click answers a card offers: only where one call does the whole job.

    Registering, reporting a score or disputing one needs a form, so those
    cards link to the site instead. A missing id leaves the card without the
    button rather than with one that cannot work.
    """
    tournament_id = payload.get("tournament_id")
    invite_id = payload.get("invite_id")
    if kind == "team_invite.received" and isinstance(invite_id, int):
        return [
            DiscordActionButton(
                label=labels["invite.accept"], action="invite.accept", target=str(invite_id), style="success"
            ),
            DiscordActionButton(
                label=labels["invite.decline"], action="invite.decline", target=str(invite_id), style="danger"
            ),
        ]
    if not isinstance(tournament_id, int):
        return []
    view = DiscordActionButton(label=labels["registration.view"], action="registration.view", target=str(tournament_id))
    if kind == "check_in.opened":
        check_in = DiscordActionButton(
            label=labels["check_in"], action="check_in", target=str(tournament_id), style="success"
        )
        return [check_in, view]
    if kind in ("registration.approved", "registration.rejected"):
        return [view]
    return []


def render_discord(
    kind: str,
    payload: Mapping[str, Any],
    *,
    locale: str,
    site_url: str,
    workspace_name: str | None = None,
    image_url: str | None = None,
    personal: bool = False,
) -> DiscordCard:
    """The card for one notification, in ``locale``.

    ``workspace_name`` is the organizer line above the heading, ``image_url``
    the picture beside it (tournament logo, else workspace icon), and
    ``personal`` marks a DM: it adds the small button that opens its reader's
    way to switch Discord DMs off -- a channel post has no single reader.

    An unknown locale falls back to ``ru`` (the platform default) rather than
    failing a delivery over a settings value; an unknown *kind* raises, because
    silently posting nothing would hide a missing template forever.
    """
    locale = locale if locale in TEMPLATES else "ru"
    template = TEMPLATES[locale].get(kind)
    if template is None:
        raise ValueError(f"no Discord template for notification kind {kind!r}")

    heading, sentence, detail_lines = template
    fields = _fields(kind, payload, locale)

    text = f"### {heading}\n{sentence.format_map(fields)}"
    if workspace_name and workspace_name.strip():
        text = f"-# {_escape(_clip(workspace_name.strip(), _NAME_LIMIT))}\n{text}"

    # A detail line needs every value it names: an absent ``closes_at`` or an
    # empty ``reason`` drops the line, and the sentence still stands on its own.
    # The sentence itself is strict -- a KeyError there is a template bug.
    details = [
        line.format_map(fields) for line in detail_lines if all(fields.get(name) for name in _PLACEHOLDER.findall(line))
    ]

    color = _ANSWER_COLORS.get(str(payload.get("answer")), _BLUE) if kind == "team_invite.answered" else _COLORS[kind]

    base = site_url.rstrip("/")
    onward: list[DiscordButton] = []
    path = deep_link_path(kind, payload)
    if path is not None:
        onward.append(DiscordLinkButton(label=_LINK_LABELS[locale][_destination(kind)], url=f"{base}{path}"))
    if personal:
        onward.append(DiscordActionButton(label=_MENU_LABEL, action="notifications.menu", target="all"))

    return DiscordCard(
        accent_color=color,
        text=text,
        details="\n".join(details) or None,
        # Discord only fetches absolute http(s) media; anything else is a 400.
        thumbnail_url=image_url if image_url and image_url.startswith(("https://", "http://")) else None,
        # Answers in the card; where to read more and how to stop hearing it under it.
        answers=_action_row(kind, payload, _ACTION_LABELS[locale]),
        rows=[onward] if onward else [],
    )
