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

from shared.domain.discord_ui import ROLE_EMOJI, division_emoji, emoji
from shared.domain.mix_lobby import LOBBY_LETTERS, MAX_LOBBIES
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

__all__ = (
    "LINK_BLOCKERS",
    "MIX_BLOCKERS",
    "Locale",
    "error_text",
    "locale_of",
    "mix_blocker_text",
    "mix_text",
    "registration_text",
    "role_label",
    "seat_modal_text",
    "settle_note",
    "success_text",
    "text",
)

Locale = Literal["ru", "en"]


def locale_of(locale: discord.Locale | str | None) -> Locale:
    return "ru" if str(locale or "").lower().startswith("ru") else "en"


_TEXT: dict[Locale, dict[str, str]] = {
    "ru": {
        "not_linked": "### Discord не привязан\n1. Откройте профиль на сайте\n2. Привяжите Discord",
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
        "mix_join": "Записаться",
        "mix_leave": "Выписаться",
        "mix_setup": "Настроить роли",
        "mix_none": "Сейчас нет открытого микса.",
        "open_profile": "Открыть профиль",
    },
    "en": {
        "not_linked": "### Discord isn't linked\n1. Open your profile on the site\n2. Link Discord",
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
        "mix_join": "Join",
        "mix_leave": "Leave",
        "mix_setup": "Edit roles",
        "mix_none": "No mix is open right now.",
        "open_profile": "Open profile",
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
        "invite.accept": f"{emoji('ok')} Вы приняли приглашение",
        "invite.decline": "Вы отклонили приглашение",
        "check_in": f"{emoji('ok')} Чек-ин пройден",
    },
    "en": {
        "invite.accept": f"{emoji('ok')} You accepted this invite",
        "invite.decline": "You declined this invite",
        "check_in": f"{emoji('ok')} Checked in",
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
        "checked_in": f"{emoji('ok')} пройден",
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
        "checked_in": f"{emoji('ok')} done",
        "not_checked_in": "not yet",
        "queue": "Queue position",
        "of": "of",
    },
}


_MIX: dict[Locale, dict[str, str]] = {
    "ru": {
        "heading": "Микс «{name}»",
        "seat_pool": "Вы в пуле",
        "seat_benched": "Вы на скамейке",
        "seat_must_play": "Вы в составе",
        "no_seat": "Вы не записаны на этот микс.",
        "all_ranked": "все роли с рангом",
        "no_rank": "без ранга",
        "not_playing": "не играете",
        "flex": "Флекс",
        "flex_on": "вкл",
        "flex_off": "выкл",
        "unranked": "Нет ранга: {roles} — хост проставит",
        "in_lobby": "Лобби {letter}",
        "waiting_seat": "Ждёте места",
    },
    "en": {
        "heading": "Mix “{name}”",
        "seat_pool": "You're in the pool",
        "seat_benched": "You're on the bench",
        "seat_must_play": "You're on the floor",
        "no_seat": "You're not signed up for this mix.",
        "all_ranked": "every role you have a rank in",
        "no_rank": "no rank",
        "not_playing": "not playing",
        "flex": "Flex",
        "flex_on": "on",
        "flex_off": "off",
        "unranked": "No rank yet: {roles} — the host will fill it in",
        "in_lobby": "Lobby {letter}",
        "waiting_seat": "Waiting for a seat",
    },
}

#: The seat form itself: a modal shows plain labels, so no shortcode may ride
#: along here -- Discord renders none of them outside message content.
_MODAL: dict[Locale, dict[str, str]] = {
    "ru": {
        "title": "Моё место",
        "role1": "1-я роль",
        "role2": "2-я роль",
        "role3": "3-я роль",
        "role1_hint": "Главная роль — её хост ставит первой",
        "role_hint": "Необязательно",
        "any_ranked": "Любая с рангом",
        "none": "—",
        "flex": "Флекс",
        "flex_hint": "Готов играть не за свою роль, если так лучше для баланса",
    },
    "en": {
        "title": "My seat",
        "role1": "1st role",
        "role2": "2nd role",
        "role3": "3rd role",
        "role1_hint": "Your main role — the host seats you there first",
        "role_hint": "Optional",
        "any_ranked": "Any ranked role",
        "none": "—",
        "flex": "Flex",
        "flex_hint": "Happy to play off-role when it balances the lobby better",
    },
}

#: Why a mix refused, by the code ``mix_self_policy`` named. ``bad_values`` is
#: the bot's own: a seat form value it never minted, refused before any call.
_MIX_BLOCKERS: dict[Locale, dict[str, str]] = {
    "ru": {
        "mix_closed": "Микс уже завершён или отменён.",
        "discord_not_linked": "Этот Discord не привязан к аккаунту OWT — привяжите его в профиле.",
        "battlenet_not_linked": "К аккаунту не привязан Battle.net — привяжите его в профиле.",
        "player_not_linked": "К аккаунту не привязан игрок — привяжите Battle.net в профиле.",
        "self_join_denied": "Самозапись на миксы для вас закрыта.",
        "already_joined": "Вы уже записаны на этот микс.",
        "not_on_roster": "Вы не записаны на этот микс.",
        "signup_closed": "Запись на этот микс закрыта.",
        "roster_full": "В миксе уже 100 игроков — свободных мест нет.",
        "role_edit_off": "Хост не разрешил игрокам менять роли.",
        "bad_values": "Не удалось разобрать выбор ролей — откройте микс ещё раз.",
    },
    "en": {
        "mix_closed": "This mix is already finished or cancelled.",
        "discord_not_linked": "This Discord account isn't linked to an OWT account — link it in your profile.",
        "battlenet_not_linked": "No Battle.net account is linked to yours — link it in your profile.",
        "player_not_linked": "No player is linked to your account — link Battle.net in your profile.",
        "self_join_denied": "Signing yourself up for mixes is turned off for you.",
        "already_joined": "You're already signed up for this mix.",
        "not_on_roster": "You're not signed up for this mix.",
        "signup_closed": "Sign-up for this mix is closed.",
        "roster_full": "This mix already has 100 players — no seats left.",
        "role_edit_off": "The host hasn't let players change their roles.",
        "bad_values": "Couldn't read that role pick — open the mix again.",
    },
}

#: Every refusal the bot words itself; anything else is the service's message.
MIX_BLOCKERS: frozenset[str] = frozenset(_MIX_BLOCKERS["ru"])
#: The refusals a profile link can actually fix.
LINK_BLOCKERS: frozenset[str] = frozenset({"discord_not_linked", "battlenet_not_linked", "player_not_linked"})


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
    # ``.get(default)`` would escape every known code too, for nothing: a seat
    # panel names each of the three roles on a line of its own.
    known = _ROLES[locale].get(str(code))
    return known if known is not None else escape_markdown(str(code))


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


def mix_blocker_text(locale: Locale, code: str) -> str:
    return _MIX_BLOCKERS[locale][code]


#: One per role slot of the seat form: the host reads the pick as a priority,
#: so the panel numbers it rather than spelling "first, then".
_SLOT_NUMBERS = ("①", "②", "③")


def _role_emoji(code: Any) -> str:
    name = ROLE_EMOJI.get(str(code))
    return f"{emoji(name)} " if name else ""


def _rank_text(locale: Locale, seat: Mapping[str, Any], role: str) -> str:
    """``:owt_div_gold_3: Gold 3 · 3200`` -- the division badge, its name and the SR.

    ``divisions`` is the workspace grid's answer and may be missing entirely
    (an older balancer, or a workspace with no grid); then the SR alone is the
    rank, and a role with neither is simply unranked.
    """
    ranks = seat.get("ranks")
    rank = ranks.get(role) if isinstance(ranks, Mapping) else None
    divisions = seat.get("divisions")
    division = divisions.get(role) if isinstance(divisions, Mapping) else None

    parts: list[str] = []
    if isinstance(division, Mapping) and division.get("name"):
        badge = division_emoji(division.get("slug"))
        parts.append(f"{badge} {escape_markdown(str(division['name']))}".strip())
    if rank is not None:
        parts.append(escape_markdown(str(rank)))
    return " · ".join(parts) or _MIX[locale]["no_rank"]


def _has_rank(seat: Mapping[str, Any], role: str) -> bool:
    ranks = seat.get("ranks")
    divisions = seat.get("divisions")
    return (isinstance(ranks, Mapping) and ranks.get(role) is not None) or (
        isinstance(divisions, Mapping) and divisions.get(role) is not None
    )


def _roles_block(locale: Locale, seat: Mapping[str, Any]) -> list[str]:
    """The seat's roles, one line each: the picked ones in order, the rest greyed out."""
    words = _MIX[locale]
    roles = seat.get("roles")
    if not isinstance(roles, list):
        # "Every role I have a rank in": no order to show, so no numbers --
        # just which roles that turns out to be right now.
        ranked = [role for role in REGISTRATION_ROLE_CODES if _has_rank(seat, role)]
        lines = [f"{emoji('ok')} {words['all_ranked']}"]
        lines += [f"{_role_emoji(role)}{_role(locale, role)} — {_rank_text(locale, seat, role)}" for role in ranked]
        return lines

    picked = [str(role) for role in roles]
    lines = [
        f"{_SLOT_NUMBERS[index]} {_role_emoji(role)}{_role(locale, role)} — {_rank_text(locale, seat, role)}"
        for index, role in enumerate(picked[: len(_SLOT_NUMBERS)])
    ]
    # Three indent spaces, not a number: these are the roles the host must not
    # seat them in, and they are here so the panel answers "and the others?".
    lines += [
        f"   {_role_emoji(role)}{_role(locale, role)} — {words['not_playing']}"
        for role in REGISTRATION_ROLE_CODES
        if role not in picked
    ]
    return lines


def mix_text(locale: Locale, state: Mapping[str, Any]) -> tuple[str, str]:
    """The caller's own seat in a mix (the ``self_*`` answer): ``(heading, details)``.

    Two halves because the card draws a divider between them: above it the one
    line that answers "am I in?", below it the roles the host will seat by.
    """
    words = _MIX[locale]
    head = [f"### {words['heading'].format(name=escape_markdown(str(state.get('name') or '')))}"]
    raw_seat = state.get("seat")
    seat: Mapping[str, Any] | None = raw_seat if isinstance(raw_seat, Mapping) else None

    details: list[str] = []
    if seat is None:
        head.append(words["no_seat"])
    else:
        participation = str(seat.get("participation") or "pool")
        badge = {"benched": "bench", "must_play": "starter"}.get(participation, "ok")
        status = [f"{emoji(badge)} {words.get(f'seat_{participation}', words['seat_pool'])}"]
        lobby_count = int(state.get("lobby_count") or 1)
        # Only a multi-lobby mix has a question here: which of the games is
        # theirs, and whether a balance has seated them in one at all.
        if lobby_count > 1:
            lobby = seat.get("current_lobby")
            in_range = isinstance(lobby, int) and 0 <= lobby < min(lobby_count, MAX_LOBBIES)
            letter = LOBBY_LETTERS[lobby] if in_range else ""
            status.append(
                f"{emoji(f'lobby_{letter.lower()}')} {words['in_lobby'].format(letter=letter)}"
                if letter
                else f"{emoji('clock')} {words['waiting_seat']}"
            )
        head.append(" · ".join(status))
        details += _roles_block(locale, seat)
        details.append(
            f"{emoji('flex')} {words['flex']}: {words['flex_on'] if seat.get('is_flex') else words['flex_off']}"
        )

    unranked = list(state.get("unranked_roles") or [])
    if unranked:
        named = ", ".join(_role(locale, role) for role in unranked)
        details.append(f"-# {emoji('warn')} " + words["unranked"].format(roles=named))

    policy = state.get("policy")
    blocker = policy.get("edit_blocker") if isinstance(policy, Mapping) else None
    if blocker == "role_edit_off":
        details.append(f"-# {emoji('lock')} " + _MIX_BLOCKERS[locale]["role_edit_off"])
    return "\n".join(head), "\n".join(details)


def seat_modal_text(locale: Locale) -> Mapping[str, str]:
    """The seat form's own words (``cards.seat_modal``); role names come from :func:`role_label`."""
    return _MODAL[locale]


def role_label(locale: Locale, code: Any) -> str:
    return _role(locale, code)
