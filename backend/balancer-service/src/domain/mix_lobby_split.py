"""Делит пул микса на два равных по силе лобби.

Pure domain algorithm: no I/O, no async, no ORM. Вызывающий
(``CustomGameService.balance`` со ``scope="all"``) резолвит ранги, порядок
ролей и приоритет ротации, а точную рассадку внутри лобби делает прежний
``mix_balancer`` -- здесь решается только, КТО с кем в одном лобби.

``strength`` -- приближение (рейтинг роли, на которую игрока посадят первой),
поэтому фактический разрыв между лобби считается потом по ``average_mmr``
выбранных вариантов. Жадное деление плюс локальные обмены -- не глобальный
оптимум: если разрыв на практике окажется заметным, здесь появится точный
перебор делений.

Детерминизм обязателен: один и тот же пул должен делиться одинаково при
каждом нажатии. Все сортировки доломаны до входного порядка кандидатов, RNG
нет, множества нигде не обходятся.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.matching import maximum_bipartite_matching

__all__ = ("LobbySplit", "LobbySplitError", "SplitCandidate", "split_into_lobbies")

#: Потолок спеки: ровно два лобби (CHECK ``lobby_index BETWEEN 0 AND 1``).
_LOBBIES = (0, 1)

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
    lobbies: tuple[tuple[int, ...], tuple[int, ...]]
    waiting: tuple[int, ...] = ()


class LobbySplitError(ValueError):
    """Почему пул не делится. ``code`` уходит на провод как ``detail`` 422:
    ``not_enough_for_two_lobbies``, ``too_many_must_play``, ``too_many_pinned``,
    ``roles_infeasible``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _slots(mask: Mapping[str, int]) -> tuple[_Slot, ...]:
    """Ролевые слоты обоих лобби: две команды на лобби, ``mask`` слотов на команду."""
    return tuple(
        (lobby, role, position) for lobby in _LOBBIES for role, count in mask.items() for position in range(count * 2)
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
    """Заполнимы ли роли ОБОИХ лобби при этой (частичной) расстановке.

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


def split_into_lobbies(candidates: Sequence[SplitCandidate], *, mask: Mapping[str, int]) -> LobbySplit:
    """Разделить пул на два лобби по ``mask`` слотов на команду.

    1. Кто играет: ``must_play`` -> ``rotation_priority`` по возрастанию ->
       входной порядок; первые ``2 * seats`` играют, остальные ждут. Обещанных
       мест (``must_play``) больше, чем мест вообще -- отказ целиком.
    2. Закреплённые садятся в своё лобби.
    3. Остальные по убыванию силы -- в лобби полегче, если после хода роли
       обоих лобби ещё заполнимы.
    4. Пока есть незакреплённая пара, обмен которой уменьшает разрыв и
       сохраняет заполнимость, меняем лучшую такую пару.
    """
    seats = 2 * sum(mask.values())
    order = {candidate.member_id: position for position, candidate in enumerate(candidates)}
    playable = [candidate for candidate in candidates if candidate.ratings]
    if len(playable) < 2 * seats:
        raise LobbySplitError("not_enough_for_two_lobbies")
    if sum(candidate.must_play for candidate in playable) > 2 * seats:
        # Пин обещает место, а их на два лобби ровно ``2 * seats``: тихо
        # отправить часть обещанных в ``waiting`` -- сломать само обещание.
        raise LobbySplitError("too_many_must_play")

    ranked = sorted(
        playable,
        key=lambda candidate: (not candidate.must_play, candidate.rotation_priority, order[candidate.member_id]),
    )
    playing = ranked[: 2 * seats]
    seated_ids = {candidate.member_id for candidate in playing}
    waiting = tuple(candidate.member_id for candidate in candidates if candidate.member_id not in seated_ids)

    assignment: dict[int, int] = {}
    counts = [0, 0]
    totals = [0, 0]
    for candidate in playing:
        if candidate.pin is None:
            continue
        if counts[candidate.pin] >= seats:
            raise LobbySplitError("too_many_pinned")
        assignment[candidate.member_id] = candidate.pin
        counts[candidate.pin] += 1
        totals[candidate.pin] += candidate.strength

    slots = _slots(mask)
    rest = sorted(
        (candidate for candidate in playing if candidate.member_id not in assignment),
        key=lambda candidate: (-candidate.strength, order[candidate.member_id]),
    )
    for candidate in rest:
        options = sorted(
            (index for index in _LOBBIES if counts[index] < seats), key=lambda index: (totals[index], index)
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
    # Каждая итерация строго уменьшает разрыв, так что цикл конечен и без
    # потолка; ``seats ** 2`` -- страховка спеки от патологического входа.
    for _ in range(seats * seats):
        gap = abs(totals[0] - totals[1])
        improving = []
        for first in swappable:
            if assignment[first.member_id] != 0:
                continue
            for second in swappable:
                if assignment[second.member_id] != 1:
                    continue
                moved = abs(totals[0] - totals[1] + 2 * (second.strength - first.strength))
                if moved < gap:
                    improving.append((moved, order[first.member_id], order[second.member_id], first, second))
        improving.sort(key=lambda item: item[:3])
        for _moved, _first_position, _second_position, first, second in improving:
            assignment[first.member_id], assignment[second.member_id] = 1, 0
            if _fillable(playing, slots, assignment):
                totals[0] += second.strength - first.strength
                totals[1] += first.strength - second.strength
                break
            assignment[first.member_id], assignment[second.member_id] = 0, 1
        else:
            break

    seated = tuple(
        tuple(candidate.member_id for candidate in playing if assignment[candidate.member_id] == lobby)
        for lobby in _LOBBIES
    )
    return LobbySplit(lobbies=(seated[0], seated[1]), waiting=waiting)
