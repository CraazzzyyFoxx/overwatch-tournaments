"""What the bot says back when a button is pressed, in the clicker's language.

Replies go to one person (ephemeral), so they follow *that person's* Discord
client language rather than the card's: a Russian DM clicked from an English
client answers in English. Russian for ``ru``, English for everything else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

import discord
from discord.utils import escape_markdown

from shared.domain.mix_lobby import LOBBY_LETTERS, MAX_LOBBIES
from src.ui import ROLE_EMOJI, art_drawn_for, division_emoji, emoji

__all__ = (
    "LINK_BLOCKERS",
    "Locale",
    "MIX_BLOCKERS",
    "VOICE_REFUSALS",
    "discipline_roles",
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
    "voice_prompt_text",
    "voice_text",
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
        # A log-upload reply (``src.feedback``); the emoji and the error ride outside.
        "log_awaiting_link": "{filename} — загружен; администратору нужно привязать лог к игре и повторить обработку",
        "log_processing_failed": "{filename} — загружен, но обработка завершилась ошибкой",
        "log_upload_failed": "{filename} — не удалось загрузить или поставить в обработку",
        # The ``/mix`` command group (``src.cogs.interactions``).
        "slash_mix": "Микс",
        "slash_seat": "Моё место в текущем миксе",
        "slash_move": "Развести игроков по войсам команд",
        "slash_return": "Вернуть всех из войсов команд в общий",
        "slash_mix_option": "Микс, который вы ведёте",
        "slash_lobby_option": "Какое лобби",
        "slash_all_lobbies": "Все лобби",
        "slash_lobby": "Лобби {letter}",
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
        "log_awaiting_link": "{filename} — uploaded; an admin needs to link the log to a game and process it again",
        "log_processing_failed": "{filename} — uploaded, but processing failed",
        "log_upload_failed": "{filename} — could not be uploaded or queued for processing",
        "slash_mix": "Mix",
        "slash_seat": "My seat in the current mix",
        "slash_move": "Move players into their team voice channels",
        "slash_return": "Move everyone from the team voice channels back to the general one",
        "slash_mix_option": "A mix you host",
        "slash_lobby_option": "Which lobby",
        "slash_all_lobbies": "All lobbies",
        "slash_lobby": "Lobby {letter}",
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
        "voice_not_configured": "В настройках workspace не выбрана категория войсов.",
        "general_voice_not_configured": "У микса не выбран общий войс.",
        "general_voice_outside_category": "Общий войс микса больше не в категории — выберите его заново.",
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
        "voice_not_configured": "The workspace has no voice category.",
        "general_voice_not_configured": "This mix has no general voice.",
        "general_voice_outside_category": "The mix's general voice is no longer in the category — pick it again.",
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
        "rank": "Ранг",
        "away": "Вы отошли: пока не вернётесь, баланс вас не сажает",
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
        "rank": "Rank",
        "away": "You're away: no balance seats you until you're back",
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
        # Q5: a game with more roles than slots (LoL's five positions); its whole order is the site's.
        "role1_hint_long": "Главная роль. Полный порядок всех {count} ролей задаётся на сайте",
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
        "role1_hint_long": "Your main role. The full order of all {count} is set on the site",
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
        "riot_not_linked": "К аккаунту не привязан Riot — привяжите его в профиле.",
        "steam_not_linked": "К аккаунту не привязан Steam — привяжите его в профиле.",
        "player_not_linked": "К аккаунту ещё не привязан профиль игрока — привяжите его в профиле на сайте.",
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
        "riot_not_linked": "No Riot account is linked to yours — link it in your profile.",
        "steam_not_linked": "No Steam account is linked to yours — link it in your profile.",
        "player_not_linked": "Your account isn't linked to a player profile yet — link one in your profile on the site.",
        "self_join_denied": "Signing yourself up for mixes is turned off for you.",
        "already_joined": "You're already signed up for this mix.",
        "not_on_roster": "You're not signed up for this mix.",
        "signup_closed": "Sign-up for this mix is closed.",
        "roster_full": "This mix already has 100 players — no seats left.",
        "role_edit_off": "The host hasn't let players change their roles.",
        "bad_values": "Couldn't read that role pick — open the mix again.",
    },
}

#: A voice move's report, by the status the balancer gave each person.
_VOICE: dict[Locale, dict[str, str]] = {
    "ru": {
        "heading": "### Перенесено: {count}",
        "nobody": "Никого не нужно было переносить.",
        "not_in_voice": "Не в войсе",
        "no_discord_link": "Discord не привязан",
        "missing_permission": "Боту не хватает прав",
        "channel_outside_category": "Войс вне категории",
        "not_configured": "Войс команды не выбран",
        "failed": "Discord отказал",
    },
    "en": {
        "heading": "### Moved: {count}",
        "nobody": "Nobody needed moving.",
        "not_in_voice": "Not in a voice",
        "no_discord_link": "No Discord linked",
        "missing_permission": "The bot lacks permissions",
        "channel_outside_category": "Voice outside the category",
        "not_configured": "No team voice picked",
        "failed": "Discord refused",
    },
}

#: The question ``voice.move|return`` asks before anyone is moved.
_VOICE_PROMPT: dict[Locale, dict[str, str]] = {
    "ru": {
        "voice.move": "### Развести игроков по войсам команд?",
        "voice.return": "### Вернуть всех из войсов команд в общий?",
        "mix": "Микс «{name}»",
        "lobby": "Лобби {letter}",
        "all_lobbies": "Все лобби",
        "confirm": "Подтвердить",
    },
    "en": {
        "voice.move": "### Move players into their team voices?",
        "voice.return": "### Return everyone from the team voices to the general one?",
        "mix": "Mix “{name}”",
        "lobby": "Lobby {letter}",
        "all_lobbies": "All lobbies",
        "confirm": "Confirm",
    },
}

#: Every refusal the bot words itself; anything else is the service's message.
MIX_BLOCKERS: frozenset[str] = frozenset(_MIX_BLOCKERS["ru"])
#: The refusals a profile link can actually fix.
LINK_BLOCKERS: frozenset[str] = frozenset(
    {"discord_not_linked", "battlenet_not_linked", "riot_not_linked", "steam_not_linked", "player_not_linked"}
)
#: The voice refusals the balancer sends as a bare 409 detail; a 503 is said by
#: the generic "the bot is offline" card instead, so it is not one of these.
VOICE_REFUSALS: frozenset[str] = frozenset(
    {"voice_not_configured", "general_voice_not_configured", "general_voice_outside_category"}
)


def text(locale: Locale, key: str, **values: str) -> str:
    return _TEXT[locale][key].format(**values)


def success_text(locale: Locale, action: str) -> str:
    return _SUCCESS[locale][action]


def settle_note(locale: Locale, action: str) -> str:
    return f"-# {_SETTLED[locale][action]}"


def error_text(locale: Locale, code: str | None, message: str) -> str:
    known = _ERRORS[locale].get(code or "")
    return known or text(locale, "failed", message=escape_markdown(message or code or "error"))


def _role(locale: Locale, code: Any, label: str | None = None) -> str:
    # The platform's own word for a known code; otherwise the game's own name
    # for it (a LoL position) or, failing both, the code itself -- escaped.
    known = _ROLES[locale].get(str(code))
    return known if known is not None else escape_markdown(label or str(code))


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
            _role(locale, role["role"]["role"]) + (f" ({card['primary']})" if role.get("is_primary") else "")
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
_SLOT_NUMBERS = ("①", "②", "③", "④", "⑤")


def _role_emoji(code: Any) -> str:
    name = ROLE_EMOJI.get(str(code))
    return f"{emoji(name)} " if name else ""


def _rank_text(locale: Locale, seat: Mapping[str, Any], role: str, discipline: str) -> str:
    """``:owt_div_gold_3: Gold 3 · 3200`` -- the division badge, its name and the number.

    The badge is the emblem of the tier the number lands in on the game's own
    ladder, and only a seat that wears one names its division: a game without
    a ladder ranks on the organiser's grid, whose tiers are bare numbers.
    ``divisions`` may be missing entirely (an older balancer); then the number
    alone is the rank, and a role with neither is simply unranked.
    """
    ranks = seat.get("ranks")
    rank = ranks.get(role) if isinstance(ranks, Mapping) else None
    divisions = seat.get("divisions")
    division = divisions.get(role) if isinstance(divisions, Mapping) else None

    parts: list[str] = []
    badge = division_emoji(discipline, rank)
    if badge and isinstance(division, Mapping) and division.get("name"):
        parts.append(f"{badge} {escape_markdown(str(division['name']))}")
    if rank is not None:
        parts.append(escape_markdown(str(rank)))
    return " · ".join(parts) or _MIX[locale]["no_rank"]


def _has_rank(seat: Mapping[str, Any], role: str) -> bool:
    ranks = seat.get("ranks")
    divisions = seat.get("divisions")
    return (isinstance(ranks, Mapping) and ranks.get(role) is not None) or (
        isinstance(divisions, Mapping) and divisions.get(role) is not None
    )


def _roles_block(
    locale: Locale, seat: Mapping[str, Any], roles: Sequence[tuple[str, str]], discipline: str
) -> list[str]:
    """The seat's roles, one line each: the picked ones in order, the rest of the game's greyed out."""
    words = _MIX[locale]
    labels = dict(roles)
    overwatch = art_drawn_for(discipline)

    def line(prefix: str, role: str, tail: str) -> str:
        mark = _role_emoji(role) if overwatch else ""
        return f"{prefix}{mark}{_role(locale, role, labels.get(role))} — {tail}"

    chosen = seat.get("roles")
    if not isinstance(chosen, list):
        # "Every role I have a rank in": no order to show, so no numbers --
        # just which roles that turns out to be right now.
        ranked = [code for code, _label in roles if _has_rank(seat, code)]
        return [
            f"{emoji('ok')} {words['all_ranked']}",
            *(line("", role, _rank_text(locale, seat, role, discipline)) for role in ranked),
        ]

    picked = [role["role"] for role in chosen]
    lines = [
        line(f"{_SLOT_NUMBERS[index]} ", role, _rank_text(locale, seat, role, discipline))
        for index, role in enumerate(picked[: len(_SLOT_NUMBERS)])
    ]
    # Three indent spaces, not a number: these are the roles the host must not
    # seat them in, and they are here so the panel answers "and the others?".
    lines += [line("   ", code, words["not_playing"]) for code, _label in roles if code not in picked]
    return lines


def discipline_roles(state: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The mix game's rated roles as ``(code, label)`` -- the self state's ``discipline_roles`` (spec §12.1 R3-1)."""
    return [
        (str(role["code"]), str(role.get("label") or role["code"]))
        for role in state.get("discipline_roles") or ()
        if isinstance(role, Mapping) and role.get("code")
    ]


def mix_text(locale: Locale, state: Mapping[str, Any]) -> tuple[str, str]:
    """The caller's own seat in a mix (the ``self_*`` answer): ``(heading, details)``.

    Two halves because the card draws a divider between them: above it the one
    line that answers "am I in?", below it the roles the host will seat by --
    the game's own, none at all in a one-role game, which shows the rank alone
    (spec §12.1 R3-1) -- and whether the player is away.
    """
    words = _MIX[locale]
    roles = discipline_roles(state)
    labels = dict(roles)
    discipline = str(state.get("discipline") or "")
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
        if len(roles) > 1:
            details += _roles_block(locale, seat, roles, discipline)
            if state.get("discipline_flex"):
                details.append(
                    f"{emoji('flex')} {words['flex']}: {words['flex_on'] if seat.get('is_flex') else words['flex_off']}"
                )
        elif roles:
            details.append(f"{words['rank']}: {_rank_text(locale, seat, roles[0][0], discipline)}")
        if seat.get("away"):
            details.append(f"{emoji('clock')} {words['away']}")

    unranked = list(state.get("unranked_roles") or [])
    if unranked:
        named = ", ".join(_role(locale, role, labels.get(role)) for role in unranked)
        details.append(f"-# {emoji('warn')} " + words["unranked"].format(roles=named))

    policy = state.get("policy")
    blocker = policy.get("edit_blocker") if isinstance(policy, Mapping) else None
    if blocker == "role_edit_off":
        details.append(f"-# {emoji('lock')} " + _MIX_BLOCKERS[locale]["role_edit_off"])
    return "\n".join(head), "\n".join(details)


def voice_text(locale: Locale, report: Mapping[str, Any]) -> tuple[str, str | None]:
    """A move's report: how many moved, then everyone who was not, grouped by why."""
    words = _VOICE[locale]
    results = [row for row in report.get("results") or [] if isinstance(row, Mapping)]
    if not results:
        return words["heading"].format(count=0), words["nobody"]
    missed: dict[str, list[str]] = {}
    for row in results:
        status = str(row.get("status"))
        if status != "moved":
            missed.setdefault(status, []).append(escape_markdown(str(row.get("name") or "?")))
    lines = [f"**{words.get(status, status)}:** {', '.join(names)}" for status, names in missed.items()]
    heading = words["heading"].format(count=sum(row.get("status") == "moved" for row in results))
    return heading, "\n".join(lines) or None


def voice_prompt_text(
    locale: Locale, action_name: str, mix_name: str | None, lobby_index: int | None
) -> tuple[str, str]:
    """``(question, confirm label)`` for a voice control: what will happen, to which mix and lobby."""
    words = _VOICE_PROMPT[locale]
    where = words["all_lobbies"] if lobby_index is None else words["lobby"].format(letter=LOBBY_LETTERS[lobby_index])
    if mix_name:
        where = f"{words['mix'].format(name=escape_markdown(mix_name))} · {where}"
    return f"{words[action_name]}\n{where}", words["confirm"]


def seat_modal_text(locale: Locale) -> Mapping[str, str]:
    """The seat form's own words (``cards.seat_modal``); role names come from :func:`role_label`."""
    return _MODAL[locale]


def role_label(locale: Locale, code: Any, label: str | None = None) -> str:
    return _role(locale, code, label)
