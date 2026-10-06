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
  ``<@id>`` a mention. Pings are off at the bot as well (``allow_mentions``
  defaults to ``False``), so a ``<@id>`` that survived escaping still pings nobody.
* **Emoji are named, never pasted.** A heading and a button carry the bot's own
  emoji as a ``:owt_<name>:`` shortcode (:mod:`shared.domain.discord_ui`), which
  discord-service swaps for the uploaded application emoji -- or for a Unicode
  fallback until one is. Nothing here depends on the picture arriving: every
  heading reads as a sentence with the emoji stripped out.
* **User text is clipped before it is escaped**, so no name or reason, however
  long, pushes a card past Discord's 4000-character limit (a 400 there parks
  the command in the DLQ instead of sending it).
* **A detail line whose field is absent is dropped**, not rendered with a hole:
  ``closes_at`` is optional and ``model_dump(exclude_none=True)`` leaves it out
  of the snapshot entirely; an empty ``reason`` means none was given.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from shared.domain.discord_ui import AMBER, BLUE, GREEN, RED, TEAL, emoji
from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard, DiscordLinkButton
from shared.services.notifications import NOTIFICATION_KINDS

__all__ = ("DELIVERABLE_KINDS", "TEMPLATES", "deep_link_path", "render_discord")

# The inbox's status palette (``NotificationList.getKindConfig``) by way of the
# shared one, so the DM reads the same as the bell *and* the same as the mix
# posts: green is good news, red is bad, amber wants action, blue is
# information, teal is the platform accent.
_COLORS: dict[str, int] = {
    "team_invite.received": BLUE,
    "team_invite.answered": BLUE,
    "registration.approved": GREEN,
    "registration.rejected": RED,
    "encounter.report_disputed": AMBER,
    "encounter.dispute_review": AMBER,
    "team.kicked": RED,
    "team.rejected": RED,
    "team.disbanded": RED,
    "registration.opened": TEAL,
    "check_in.opened": AMBER,
    "encounter.scheduled": BLUE,
}
_ANSWER_COLORS = {"accepted": GREEN, "declined": RED}

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

#: ``encounter.dispute_review`` carries ``position=0`` for a series-level
#: dispute and the 1-based map position otherwise -- the same sentinel the
#: inbox's ICU ``plural`` selects on.
_SERIES_SCOPE = {"ru": "итоговый счёт серии", "en": "the final series score"}
_MAP_SCOPE = {"ru": "карта {position}", "en": "map {position}"}

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
        "encounter.dispute_review": (
            "Нужно решение организатора",
            "Капитаны **{home_team_name}** и **{away_team_name}** разошлись в счёте.",
            ("**Что оспорено:** {disputed_scope}",),
        ),
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
        "encounter.dispute_review": (
            "Organizer decision needed",
            "**{home_team_name}** and **{away_team_name}** reported different scores.",
            ("**Disputed:** {disputed_scope}",),
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

#: ``kind -> emoji name`` for the heading (:func:`shared.domain.discord_ui.emoji`).
#: Locale-independent on purpose: a picture is the one part of a card that does
#: not need translating, and one map is one place to keep it honest. The names
#: are checked against ``EMOJI`` by the test, because a typo would reach a
#: reader as the literal text ``:owt_vs:``.
_HEADING_EMOJI: dict[str, str] = {
    "team_invite.received": "players",
    "team_invite.answered": "info",
    "registration.approved": "ok",
    "registration.rejected": "error",
    "encounter.report_disputed": "warn",
    "encounter.dispute_review": "warn",
    "team.kicked": "error",
    "team.rejected": "error",
    "team.disbanded": "error",
    "registration.opened": "join",
    "check_in.opened": "clock",
    "encounter.scheduled": "vs",
}

#: ``team_invite.answered`` is the one kind whose news is only known from the
#: payload, so its heading follows the answer the way its colour already does.
_ANSWER_EMOJI = {"accepted": "ok", "declined": "error"}

#: ``encounter.scheduled`` fires as soon as both teams are known, so the hour
#: may still be missing: then the card announces the match itself (its detail
#: line drops itself for want of ``scheduled_at``), not a time.
_NO_TIME_HEADINGS = {"ru": "Следующий матч", "en": "Next match"}

#: Link captions, one per destination. ``encounter.scheduled`` names its own
#: three (D8): the room the readers play in, and the public match page.
_LINK_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "participants": "Перейти к участникам",
        "pregame": "Открыть матч",
        "tournament": "Открыть турнир",
        "match_room": "Комната матча",
        "pick_ban": "Бан-пик",
        "match": "Матч",
    },
    "en": {
        "participants": "View participants",
        "pregame": "Open match",
        "tournament": "Open tournament",
        "match_room": "Match room",
        "pick_ban": "Pick-ban",
        "match": "Match",
    },
}

#: Captions of the buttons the bot answers itself (discord-service ``ACTIONS``),
#: and the emoji each wears.
_ACTION_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "invite.accept": "Принять",
        "invite.decline": "Отклонить",
        "check_in": "Пройти чек-ин",
        "registration.view": "Моя заявка",
        # The DM's way out, deliberately small: it opens a reply only the reader
        # sees, and the switch-everything-off button lives there, not on the card.
        "notifications.menu": "Уведомления",
    },
    "en": {
        "invite.accept": "Accept",
        "invite.decline": "Decline",
        "check_in": "Check in",
        "registration.view": "My registration",
        "notifications.menu": "Notifications",
    },
}
_ACTION_EMOJI = {
    "invite.accept": "ok",
    "invite.decline": "error",
    "check_in": "ok",
    "registration.view": "info",
    "notifications.menu": "bell_off",
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
_PREGAME_KINDS = frozenset({"encounter.report_disputed", "encounter.dispute_review", "encounter.scheduled"})
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
    if kind == "encounter.dispute_review":
        position = payload.get("position") or 0
        fields["disputed_scope"] = (
            _SERIES_SCOPE[locale] if position == 0 else _MAP_SCOPE[locale].format(position=position)
        )
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
                label=labels["invite.accept"],
                action="invite.accept",
                target=str(invite_id),
                style="success",
                emoji=_ACTION_EMOJI["invite.accept"],
            ),
            DiscordActionButton(
                label=labels["invite.decline"],
                action="invite.decline",
                target=str(invite_id),
                style="danger",
                emoji=_ACTION_EMOJI["invite.decline"],
            ),
        ]
    if not isinstance(tournament_id, int):
        return []
    view = DiscordActionButton(
        label=labels["registration.view"],
        action="registration.view",
        target=str(tournament_id),
        emoji=_ACTION_EMOJI["registration.view"],
    )
    if kind == "check_in.opened":
        check_in = DiscordActionButton(
            label=labels["check_in"],
            action="check_in",
            target=str(tournament_id),
            style="success",
            emoji=_ACTION_EMOJI["check_in"],
        )
        return [check_in, view]
    if kind in ("registration.approved", "registration.rejected"):
        return [view]
    return []


def _scheduled_links(
    payload: Mapping[str, Any], base: str, labels: Mapping[str, str], *, personal: bool
) -> list[DiscordButton]:
    """Where an ``encounter.scheduled`` card points (D8).

    A DM leads with the room its reader acts in -- the pick-ban when the match
    has one, the captains' lobby-code chat otherwise -- and offers the public
    match page second. A channel post leads with that page, and shows the room
    only when there is a pick-ban to walk into.
    """
    room = deep_link_path("encounter.scheduled", payload)
    encounter_id = payload.get("encounter_id")
    match = f"{base}/encounters/{encounter_id}" if isinstance(encounter_id, int) else None
    pick_ban = payload.get("pick_ban") is True
    buttons: list[DiscordButton] = []
    if personal and room is not None:
        buttons.append(
            DiscordLinkButton(label=labels["pick_ban" if pick_ban else "match_room"], url=f"{base}{room}", emoji="link")
        )
    if match is not None:
        buttons.append(DiscordLinkButton(label=labels["match"], url=match, emoji="link"))
    if not personal and pick_ban and room is not None:
        buttons.append(DiscordLinkButton(label=labels["pick_ban"], url=f"{base}{room}", emoji="link"))
    return buttons


def _og_image_url(payload: Mapping[str, Any], base: str) -> str | None:
    """The encounter's OpenGraph card, shown inside the Discord message itself.

    ``?v=`` is the payload's own digest: Discord caches a media URL for good,
    so a new opponent or a new time has to arrive as a new URL. The frontend
    route ignores the query -- it is a cache buster, not an argument.
    """
    encounter_id = payload.get("encounter_id")
    if not isinstance(encounter_id, int):
        return None
    snapshot = json.dumps(dict(payload), sort_keys=True, default=str)
    version = hashlib.sha1(snapshot.encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{base}/encounters/{encounter_id}/og?v={version}"


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
    badge = _HEADING_EMOJI[kind]
    if kind == "encounter.scheduled" and not payload.get("scheduled_at"):
        heading = _NO_TIME_HEADINGS[locale]
    if kind == "team_invite.answered":
        answer = str(payload.get("answer"))
        badge = _ANSWER_EMOJI.get(answer, badge)
        color = _ANSWER_COLORS.get(answer, BLUE)
    else:
        color = _COLORS[kind]
    fields = _fields(kind, payload, locale)

    text = f"### {emoji(badge)} {heading}\n{sentence.format_map(fields)}"
    if workspace_name and workspace_name.strip():
        text = f"-# {_escape(_clip(workspace_name.strip(), _NAME_LIMIT))}\n{text}"

    # A detail line needs every value it names: an absent ``closes_at`` or an
    # empty ``reason`` drops the line, and the sentence still stands on its own.
    # The sentence itself is strict -- a KeyError there is a template bug.
    details = [
        line.format_map(fields) for line in detail_lines if all(fields.get(name) for name in _PLACEHOLDER.findall(line))
    ]

    base = site_url.rstrip("/")
    labels = _LINK_LABELS[locale]
    actions = _ACTION_LABELS[locale]
    onward: list[DiscordButton]
    if kind == "encounter.scheduled":
        onward = _scheduled_links(payload, base, labels, personal=personal)
    else:
        onward = []
        path = deep_link_path(kind, payload)
        if path is not None:
            onward.append(DiscordLinkButton(label=labels[_destination(kind)], url=f"{base}{path}", emoji="link"))
    if personal:
        onward.append(
            DiscordActionButton(
                label=actions["notifications.menu"],
                action="notifications.menu",
                target="all",
                emoji=_ACTION_EMOJI["notifications.menu"],
            )
        )

    return DiscordCard(
        accent_color=color,
        text=text,
        details="\n".join(details) or None,
        # Discord only fetches absolute http(s) media; anything else is a 400.
        thumbnail_url=image_url if image_url and image_url.startswith(("https://", "http://")) else None,
        # The branding thumbnail is beside the text; this is the card's subject.
        image_url=_og_image_url(payload, base) if kind == "encounter.scheduled" else None,
        # Answers in the card; where to read more and how to stop hearing it under it.
        answers=_action_row(kind, payload, actions),
        rows=[onward] if onward else [],
    )
