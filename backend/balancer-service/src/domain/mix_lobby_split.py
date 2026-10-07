"""Делит пул микса на N равных по силе лобби.

Pure domain algorithm: no I/O, no async, no ORM. Вызывающий
(``CustomGameService.balance`` со ``scope="all"``) резолвит ранги, порядок
ролей и приоритет ротации, а точную рассадку внутри лобби делает прежний
``mix_balancer`` -- здесь решается только, КТО с кем в одном лобби.

``strength`` -- приближение (рейтинг роли, на которую игрока посадят первой),
поэтому фактический разрыв между лобби считается потом по ``average_mmr``
выбранных вариантов. Жадное деление плюс локальные обмены -- не глобальный
оптимум: если разрыв на практике окажется заметным, здесь появится точный
перебор делений.

Лобби РАВНЫ по силе, это не дивизионы: мера неравенства -- сумма квадратов
отклонений сумм лобби от среднего (для двух лобби это ровно |разрыв|).

Детерминизм обязателен: один и тот же пул должен делиться одинаково при
каждом нажатии. Все сортировки доломаны до входного порядка кандидатов, RNG
нет, множества нигде не обходятся.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shared.domain.mix_lobby import MAX_LOBBIES
from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.matching import maximum_bipartite_matching

__all__ = ("LobbySplit", "LobbySplitError", "SplitCandidate", "split_into_lobbies")

#: Слот роли одного лобби: (лобби, роль, порядковый номер слота этой роли).
_Slot = tuple[int, str, int]


@dataclass(frozen=True, slots=True)
class SplitCandidate:
    """Один не-benched игрок пула глазами делителя.

    ``ratings`` -- только роли, на которых у него нашёлся ранг; пустой словарь
    означает «не играбелен» (движок такого всё равно не посадит).
    ``strength`` -- рейтинг роли с высшим приоритетом, для ``all_ranked``
    максимум. ``rotation_priority``: меньше = больше должен место.
    """

    member_id: int
    ratings: Mapping[str, int]
    strength: int
    pin: int | None = None
    must_play: bool = False
    rotation_priority: float = 0.0


@dataclass(frozen=True, slots=True)
class LobbySplit:
    #: По кортежу на лобби, в порядке ``lobby_index``.
    lobbies: tuple[tuple[int, ...], ...]
    waiting: tuple[int, ...] = ()


class LobbySplitError(ValueError):
    """Почему пул не делится. ``code`` уходит на провод как ``detail`` 422:
    ``not_enough_players``, ``too_many_must_play``, ``too_many_pinned``,
    ``roles_infeasible``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _slots(mask: Mapping[str, int], lobby_count: int) -> tuple[_Slot, ...]:
    """Ролевые слоты всех лобби: две команды на лобби, ``mask`` слотов на команду."""
    return tuple(
        (lobby, role, position)
        for lobby in range(lobby_count)
        for role, count in mask.items()
        for position in range(count * 2)
    )


def _eligible(candidate: SplitCandidate, slot: _Slot, lobby: int | None) -> bool:
    """Может ли игрок занять слот: своё лобби (или ещё никакое) плюс роль.

    Флекс-слот берёт любого играбельного: ранга с именем ``flex`` не бывает,
    а ``resolve_roster_shape`` такую форму отдать может.
    """
    if lobby is not None and lobby != slot[0]:
        return False
    return slot[1] == FLEX_SLOT_CODE or slot[1] in candidate.ratings


def _fillable(
    playing: Sequence[SplitCandidate],
    slots: Sequence[_Slot],
    assignment: Mapping[int, int],
) -> bool:
    """Заполнимы ли роли ВСЕХ лобби при этой (частичной) расстановке.

    Уже поставленные привязаны к слотам своего лобби, остальные могут попасть
    в любое -- вместимость лобби кодируется числом его слотов, поэтому полное
    сопоставление автоматически даёт каждому лобби ровно его места.
    """
    eligible = {
        candidate.member_id: [slot for slot in slots if _eligible(candidate, slot, assignment.get(candidate.member_id))]
        for candidate in playing
    }
    matching = maximum_bipartite_matching(
        candidates=[candidate.member_id for candidate in playing],
        slots=slots,
        eligible_slots=eligible,
    )
    return matching.matched_count == len(slots)


def _spread(totals: Sequence[int]) -> int:
    """Неравенство лобби: сумма квадратов отклонений от среднего, без дробей.

    Сравниваются только значения между собой, поэтому среднее не делится, а
    домножается: ``sum((n * total - sum(totals)) ** 2)`` монотонно совпадает с
    суммой квадратов отклонений. Для двух лобби это ``2 * разрыв ** 2``.
    """
    overall = sum(totals)
    count = len(totals)
    return sum((count * total - overall) ** 2 for total in totals)


def split_into_lobbies(
    candidates: Sequence[SplitCandidate], *, mask: Mapping[str, int], lobby_count: int = 2
) -> LobbySplit:
    """Разделить пул на ``lobby_count`` лобби по ``mask`` слотов на команду.

    1. Кто играет: ``must_play`` -> ``rotation_priority`` по возрастанию ->
       входной порядок; первые ``lobby_count * seats`` играют, остальные ждут.
       Обещанных мест (``must_play``) больше, чем мест вообще -- отказ целиком.
    2. Закреплённые садятся в своё лобби.
    3. Остальные по убыванию силы -- в самое лёгкое лобби со свободным местом,
       если после хода роли всех лобби ещё заполнимы.
    4. Пока есть незакреплённая пара из РАЗНЫХ лобби, обмен которой уменьшает
       неравенство и сохраняет заполнимость, меняем лучшую такую пару.
    """
    if not 1 <= lobby_count <= MAX_LOBBIES:
        raise ValueError(f"lobby_count must be 1..{MAX_LOBBIES}, got {lobby_count}")
    seats = 2 * sum(mask.values())
    total_seats = lobby_count * seats
    order = {candidate.member_id: position for position, candidate in enumerate(candidates)}
    playable = [candidate for candidate in candidates if candidate.ratings]
    if len(playable) < total_seats:
        raise LobbySplitError("not_enough_players")
    if sum(candidate.must_play for candidate in playable) > total_seats:
        # Пин обещает место, а их на все лобби ровно ``total_seats``: тихо
        # отправить часть обещанных в ``waiting`` -- сломать само обещание.
        raise LobbySplitError("too_many_must_play")

    ranked = sorted(
        playable,
        key=lambda candidate: (not candidate.must_play, candidate.rotation_priority, order[candidate.member_id]),
    )
    playing = ranked[:total_seats]
    seated_ids = {candidate.member_id for candidate in playing}
    waiting = tuple(candidate.member_id for candidate in candidates if candidate.member_id not in seated_ids)

    assignment: dict[int, int] = {}
    counts = [0] * lobby_count
    totals = [0] * lobby_count
    for candidate in playing:
        if candidate.pin is None:
            continue
        if candidate.pin >= lobby_count or counts[candidate.pin] >= seats:
            raise LobbySplitError("too_many_pinned")
        assignment[candidate.member_id] = candidate.pin
        counts[candidate.pin] += 1
        totals[candidate.pin] += candidate.strength

    slots = _slots(mask, lobby_count)
    rest = sorted(
        (candidate for candidate in playing if candidate.member_id not in assignment),
        key=lambda candidate: (-candidate.strength, order[candidate.member_id]),
    )
    for candidate in rest:
        options = sorted(
            (index for index in range(lobby_count) if counts[index] < seats), key=lambda index: (totals[index], index)
        )
        for lobby in options:
            assignment[candidate.member_id] = lobby
            if _fillable(playing, slots, assignment):
                counts[lobby] += 1
                totals[lobby] += candidate.strength
                break
            del assignment[candidate.member_id]
        else:
            raise LobbySplitError("roles_infeasible")

    swappable = [candidate for candidate in playing if candidate.pin is None]
    # Каждая итерация строго уменьшает неравенство, так что цикл конечен и без
    # потолка; ``total_seats ** 2`` -- страховка спеки от патологического входа.
    for _ in range(total_seats * total_seats):
        spread = _spread(totals)
        improving = []
        for first in swappable:
            for second in swappable:
                left, right = assignment[first.member_id], assignment[second.member_id]
                if left >= right:
                    # Пара считается один раз, и обмен внутри лобби бессмыслен.
                    continue
                moved = list(totals)
                moved[left] += second.strength - first.strength
                moved[right] += first.strength - second.strength
                score = _spread(moved)
                if score < spread:
                    improving.append((score, order[first.member_id], order[second.member_id], first, second))
        improving.sort(key=lambda item: item[:3])
        for _score, _first_position, _second_position, first, second in improving:
            left, right = assignment[first.member_id], assignment[second.member_id]
            assignment[first.member_id], assignment[second.member_id] = right, left
            if _fillable(playing, slots, assignment):
                totals[left] += second.strength - first.strength
                totals[right] += first.strength - second.strength
                break
            assignment[first.member_id], assignment[second.member_id] = left, right
        else:
            break

    return LobbySplit(
        lobbies=tuple(
            tuple(candidate.member_id for candidate in playing if assignment[candidate.member_id] == lobby)
            for lobby in range(lobby_count)
        ),
        waiting=waiting,
    )
