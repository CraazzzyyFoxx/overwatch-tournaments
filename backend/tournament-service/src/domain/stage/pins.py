"""Pinned places of a ranked table: pure, shared by the standings service and the flow leaderboard."""

import typing


def _pin_seats(pins: typing.Mapping[int, int], size: int) -> dict[int, int]:
    """Place -> team for every pin, each at its own place inside ``1..size``.

    Pins are distinct and in range as stored; this only keeps that true when the
    table shrank under them (a team left the group). Order is kept: a pin is
    pushed below an earlier one it collides with, then the tail is pulled back
    up inside the table, so the last pinned team ends on the last place rather
    than past it.
    """
    ordered = sorted(pins.items(), key=lambda item: (item[1], item[0]))
    places: list[int] = []
    for _team_id, wanted in ordered:
        places.append(max(wanted, places[-1] + 1 if places else 1))
    ceiling = size
    for index in range(len(places) - 1, -1, -1):
        places[index] = min(places[index], ceiling)
        ceiling = places[index] - 1
    return {place: team_id for place, (team_id, _wanted) in zip(places, ordered, strict=True)}


def apply_pins(
    ranked: typing.Sequence[tuple[int, int]],
    pins: typing.Mapping[int, int],
) -> list[tuple[int, int, bool]]:
    """Seat pinned teams at their place; everyone else fills the rest in order.

    ``ranked`` is one table as the engine ranked it: ``(team_id, position)`` in
    table order, position 0 meaning "not ranked yet" (a playoff team that has not
    played). ``pins`` maps team to its fixed place; pins of teams not in the
    table are ignored. Returns ``(team_id, position, is_pinned)`` in final order.

    Unpinned teams keep their computed order, and adjacent unpinned teams that
    shared a computed place keep sharing it -- a playoff's "5th-8th" stays one
    place, under the first free seat of the run. An unpinned, unranked team stays
    at 0 and takes no seat. With no pins this returns ``ranked`` unchanged.

    A bracket mid-way ranks only the teams it eliminated, from the bottom up: the
    seats above its first ranked place are held for the teams still alive, so a
    semi loser keeps 3rd while the final is unplayed instead of closing up to 1st.
    """
    table_pins = {team_id: pins[team_id] for team_id, _position in ranked if team_id in pins}
    free = [(team_id, position) for team_id, position in ranked if team_id not in table_pins and position > 0]
    first = min((position for _team_id, position in ranked if position > 0), default=1)
    # A pinned team still alive already takes one of the held seats.
    alive_pinned = sum(1 for team_id, position in ranked if team_id in table_pins and position <= 0)
    held: list[tuple[int | None, int]] = [(None, place) for place in range(1, first - alive_pinned)]
    free = held + free
    size = len(table_pins) + len(free)
    seats = _pin_seats(table_pins, size)

    output: list[tuple[int, int, bool]] = []
    upcoming = iter(free)
    previous: tuple[int, int] | None = None  # (computed, final) of the unpinned team one seat up
    for place in range(1, size + 1):
        if place in seats:
            output.append((seats[place], place, True))
            previous = None
            continue
        team_id, computed = next(upcoming)
        position = previous[1] if previous is not None and previous[0] == computed else place
        if team_id is not None:
            output.append((team_id, position, False))
        previous = (computed, position)
    output.extend((team_id, 0, False) for team_id, position in ranked if team_id not in table_pins and position <= 0)
    return output
