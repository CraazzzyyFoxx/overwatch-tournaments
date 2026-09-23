"""What the bot says back when a button is pressed, in the clicker's language.

Replies go to one person (ephemeral), so they follow *that person's* Discord
client language rather than the card's: a Russian DM clicked from an English
client answers in English. Russian for ``ru``, English for everything else.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import discord
from discord.utils import escape_markdown

__all__ = ("Locale", "error_text", "locale_of", "registration_text", "settle_note", "success_text", "text")

Locale = Literal["ru", "en"]


def locale_of(locale: discord.Locale | str | None) -> Locale:
    return "ru" if str(locale or "").lower().startswith("ru") else "en"


_TEXT: dict[Locale, dict[str, str]] = {
    "ru": {
        "not_linked": ("Этот Discord не привязан к аккаунту OWT. Привяжите его в профиле — и кнопки заработают."),
        "inactive": "Ваш аккаунт OWT отключён.",
        "unavailable": "Сервис сейчас недоступен. Попробуйте ещё раз через минуту.",
        "failed": "Не получилось: {message}",
        "expired_button": "Эта кнопка больше не работает — откройте турнир на сайте.",
        "not_registered": "Вы не зарегистрированы на этот турнир.",
        "link_discord": "Привязать Discord",
        "notification_settings": "Настройки уведомлений",
        "mute_prompt": (
            "### Уведомления в Discord\n"
            "Отключить все личные сообщения OWT в Discord? Уведомления на сайте останутся, "
            "а включить Discord обратно можно в настройках."
        ),
        "mute_all": "Отключить все",
    },
    "en": {
        "not_linked": "This Discord account isn't linked to an OWT account. Link it in your profile and the buttons will work.",
        "inactive": "Your OWT account is deactivated.",
        "unavailable": "The service is unavailable right now. Try again in a minute.",
        "failed": "That didn't work: {message}",
        "expired_button": "This button no longer works — open the tournament on the site.",
        "not_registered": "You're not registered for this tournament.",
        "link_discord": "Link Discord",
        "notification_settings": "Notification settings",
        "mute_prompt": (
            "### Discord notifications\n"
            "Turn off every OWT direct message in Discord? Site notifications stay, "
            "and you can turn Discord back on in settings."
        ),
        "mute_all": "Turn all off",
    },
}

_SUCCESS: dict[Locale, dict[str, str]] = {
    "ru": {
        "invite.accept": "Вы в команде — приглашение принято.",
        "invite.decline": "Приглашение отклонено.",
        "check_in": "Чек-ин пройден. Удачи на турнире!",
        "notifications.mute": (
            "Готово: личные сообщения OWT в Discord отключены. Уведомления на сайте остаются, "
            "а Discord можно включить обратно в настройках."
        ),
    },
    "en": {
        "invite.accept": "You're on the team — invite accepted.",
        "invite.decline": "Invite declined.",
        "check_in": "You're checked in. Good luck!",
        "notifications.mute": (
            "Done — OWT won't message you in Discord anymore. Site notifications stay, "
            "and you can turn Discord back on in settings."
        ),
    },
}

#: The line a DM card gains when its buttons are taken off.
_SETTLED: dict[Locale, dict[str, str]] = {
    "ru": {
        "invite.accept": "✅ Вы приняли приглашение",
        "invite.decline": "Вы отклонили приглашение",
        "check_in": "✅ Чек-ин пройден",
    },
    "en": {
        "invite.accept": "✅ You accepted this invite",
        "invite.decline": "You declined this invite",
        "check_in": "✅ Checked in",
    },
}

#: Refusals worth their own sentence, by the machine code the service sends.
#: Anything else is shown as the service's own message.
_ERRORS: dict[Locale, dict[str, str]] = {
    "ru": {
        "invite_already_accepted": "Это приглашение уже принято.",
        "invite_declined": "Это приглашение уже отклонено.",
        "invite_revoked": "Капитан отозвал это приглашение.",
        "invite_expired": "Срок приглашения истёк — попросите капитана прислать новое.",
        "invite_not_for_you": "Это приглашение отправлено другому аккаунту.",
        "invite_not_found": "Приглашение не найдено.",
        "registration_terminal": "Ваша заявка на этот турнир больше не активна.",
        "already_registered": "Вы уже зарегистрированы на этот турнир.",
        "check_in_closed": "Чек-ин сейчас закрыт.",
    },
    "en": {
        "invite_already_accepted": "This invite has already been accepted.",
        "invite_declined": "This invite was already declined.",
        "invite_revoked": "The captain withdrew this invite.",
        "invite_expired": "This invite has expired — ask the captain for a new one.",
        "invite_not_for_you": "This invite was sent to a different account.",
        "invite_not_found": "Invite not found.",
        "registration_terminal": "Your registration for this tournament is no longer active.",
        "already_registered": "You're already registered for this tournament.",
        "check_in_closed": "Check-in is closed right now.",
    },
}

_STATUSES: dict[Locale, dict[str, str]] = {
    "ru": {
        "pending": "На рассмотрении",
        "approved": "Одобрена",
        "rejected": "Отклонена",
        "withdrawn": "Отозвана",
        "banned": "Заблокирована",
    },
    "en": {
        "pending": "Pending review",
        "approved": "Approved",
        "rejected": "Rejected",
        "withdrawn": "Withdrawn",
        "banned": "Banned",
    },
}

#: Same words as the frontend's ``slotCodes``; a custom roster code shows as is.
_ROLES: dict[Locale, dict[str, str]] = {
    "ru": {"tank": "Танк", "damage": "Дамаг", "support": "Саппорт", "flex": "Флекс"},
    "en": {"tank": "Tank", "damage": "Damage", "support": "Support", "flex": "Flex"},
}

_CARD: dict[Locale, dict[str, str]] = {
    "ru": {
        "heading": "Ваша заявка",
        "status": "Статус",
        "roles": "Роли",
        "primary": "основная",
        "team": "Команда",
        "substitute": "замена",
        "check_in": "Чек-ин",
        "checked_in": "✅ пройден",
        "not_checked_in": "не пройден",
        "queue": "Место в очереди",
        "of": "из",
    },
    "en": {
        "heading": "Your registration",
        "status": "Status",
        "roles": "Roles",
        "primary": "main",
        "team": "Team",
        "substitute": "substitute",
        "check_in": "Check-in",
        "checked_in": "✅ done",
        "not_checked_in": "not yet",
        "queue": "Queue position",
        "of": "of",
    },
}


def text(locale: Locale, key: str, **values: str) -> str:
    return _TEXT[locale][key].format(**values)


def success_text(locale: Locale, action: str) -> str:
    return _SUCCESS[locale][action]


def settle_note(locale: Locale, action: str) -> str:
    return f"-# {_SETTLED[locale][action]}"


def error_text(locale: Locale, code: str | None, message: str) -> str:
    known = _ERRORS[locale].get(code or "")
    return known or text(locale, "failed", message=escape_markdown(message or code or "error"))


def _role(locale: Locale, code: Any) -> str:
    return _ROLES[locale].get(str(code), escape_markdown(str(code)))


def registration_text(locale: Locale, registration: Mapping[str, Any]) -> str:
    """The caller's own registration (``RegistrationRead``) as a short card.

    A builtin status the workspace did not rename is worded here; a custom or
    renamed one shows the workspace's own name, escaped -- it is organizer text.
    """
    card = _CARD[locale]
    meta = registration.get("status_meta") or {}
    status = str(registration.get("status") or "pending")
    if meta.get("is_builtin") and not meta.get("is_override") and status in _STATUSES[locale]:
        status_label = _STATUSES[locale][status]
    else:
        status_label = escape_markdown(str(meta.get("name") or status))
    lines = [f"### {card['heading']}", f"**{card['status']}:** {status_label}"]

    roles = [role for role in registration.get("roles") or [] if isinstance(role, Mapping)]
    if roles:
        parts = [
            _role(locale, role.get("role")) + (f" ({card['primary']})" if role.get("is_primary") else "")
            for role in roles
        ]
        lines.append(f"**{card['roles']}:** {', '.join(parts)}")

    team = registration.get("team")
    if isinstance(team, Mapping) and team.get("name"):
        seat = [_role(locale, team["slot_code"])] if team.get("slot_code") else []
        if team.get("is_substitute"):
            seat.append(card["substitute"])
        suffix = f" ({', '.join(seat)})" if seat else ""
        lines.append(f"**{card['team']}:** {escape_markdown(str(team['name']))}{suffix}")

    checked = card["checked_in"] if registration.get("checked_in") else card["not_checked_in"]
    lines.append(f"**{card['check_in']}:** {checked}")

    position, total = registration.get("queue_position"), registration.get("queue_total")
    if isinstance(position, int) and isinstance(total, int):
        lines.append(f"**{card['queue']}:** {position} {card['of']} {total}")
    return "\n".join(lines)
