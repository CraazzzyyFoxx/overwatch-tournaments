"""Mix ranker: an expert's open rating corrected by a hidden Bayesian one.

Idea and specification: the mixtura-ranker project by Dmitriy (GitHub
@dmelackov), https://github.com/mixtura-dev/mixtura-ranker -- see its
``docs/MathDescription.md`` at commit ``32f3f039``. This module is an
independent implementation of that specification, not a port of its code.

Each workspace member keeps, per role, a hidden ``(mu, sigma)`` rated by
OpenSkill's Thurstone-Mosteller (full pairing) model. The open rating ``R`` is
the number a host or an expert set; ``f`` maps the hidden ordinal onto the
open scale and ``f^-1`` maps back. The two variants share everything the
specification fixes (mapping, ordinal with its sigma-fading gravity,
initialisation) and differ only in how hard the open side follows the hidden
one -- the hidden rating itself is one model per workspace, so it cannot
differ between them.

Deviations from the specification, all on purpose:

* ``beta = sigma_init / 2`` and ``tau = sigma_init / 100`` (OpenSkill's own
  default ratios) instead of the library defaults, which assume ``mu`` around
  25 while the specification's scale puts it in the hundreds -- with them the
  uncertainty collapses within a few dozen matches.
* ``corrected`` scales the gate and the post-match pull by the hidden rating's
  own uncertainty expressed in open-rating points, ``u = sigma * df/dmu``,
  instead of by the whole open range. In a synthetic replay (150 players,
  noisy expert seeds, random 5v5) that cut the effective rating's error by
  ~10% at 10-40 matches per player; ``reference`` keeps the specification's
  range scaling, which was ~9% better at ~200 matches per player.
* The open scale is centred on ``rating_avg`` by an offset inside the sigmoid,
  ``f(o) = R_min + span * sigmoid(o / s + c)`` with
  ``c = logit((R_avg - R_min) / span)``, instead of the specification's
  ``- Delta_translate`` after it. Section 2.3 promises a map onto
  ``[R_min, R_max]``; the subtraction actually lands on
  ``[R_min - Delta_translate, R_max - Delta_translate]`` (``[-100, 4900]`` at the
  defaults), so the top of the range was unreachable. ``f(0)`` is still
  ``R_avg``.
* In both variants the open rating never moves against the result: a win
  never lowers it and a loss never raises it. The ordinal's fading gravity
  can otherwise nudge a heavily favoured low-rated winner down. For the same
  reason a rating already outside ``[R_min, R_max]`` is not snapped back into
  it -- it may only move towards the range.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

from openskill.models import ThurstoneMostellerFull

__all__ = (
    "DEFAULT_SETTINGS",
    "HiddenRating",
    "Ranker",
    "RankerSettings",
    "RankerVariant",
)

RankerVariant = Literal["reference", "corrected"]

#: The specification's gate is flat for |z| < 2 and saturates past 3.
_GATE_Z_HALF = 2.0


class HiddenRating(NamedTuple):
    mu: float
    sigma: float


@dataclass(frozen=True, slots=True)
class RankerSettings:
    """One workspace's ranker knobs; field names follow the specification."""

    rating_min: float = 0.0
    rating_max: float = 5000.0
    #: The open rating an average player holds; the hidden scale is centred on it.
    rating_avg: float = 2400.0
    #: ``g``: how strongly an uncertain hidden rating is pulled to the average.
    gravity: float = 0.5
    #: ``d``: how categorical the gate between "ignore" and "correct" is.
    gate_steepness: float = 4.0
    sigma_init: float = 25.0
    variant: RankerVariant = "corrected"

    def hidden_scale(self) -> tuple[float, float, float, float]:
        """The knobs a stored ``(mu, sigma)`` is expressed in.

        Changing any of these reinterprets every stored hidden rating, so the
        workspace's ratings have to be rebuilt from its match history.
        """
        return (self.rating_min, self.rating_max, self.rating_avg, self.sigma_init)


DEFAULT_SETTINGS = RankerSettings()


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


class Ranker:
    """Every formula of the ranker for one workspace's settings."""

    def __init__(self, settings: RankerSettings = DEFAULT_SETTINGS) -> None:
        s = settings
        if not s.rating_min < s.rating_avg < s.rating_max:
            raise ValueError("rating_min < rating_avg < rating_max is required")
        if s.sigma_init <= 0 or s.gate_steepness <= 0 or s.gravity < 0:
            raise ValueError("sigma_init and gate_steepness must be positive, gravity non-negative")
        self.settings = s
        self._span = s.rating_max - s.rating_min
        #: ``s_closed``: hidden units per logit of the open scale.
        self._scale = 4.0 * s.sigma_init
        #: Centres the sigmoid on ``rating_avg``: ``f(0) == rating_avg``.
        p_avg = (s.rating_avg - s.rating_min) / self._span
        self._offset = math.log(p_avg / (1.0 - p_avg))
        self._model = ThurstoneMostellerFull(
            mu=0.0, sigma=s.sigma_init, beta=s.sigma_init / 2.0, tau=s.sigma_init / 100.0
        )

    # --- mapping between the scales -------------------------------------------------

    def _ordinal_factor(self, sigma: float) -> float:
        return 1.0 + self.settings.gravity * sigma / self.settings.sigma_init

    def _share(self, ordinal: float) -> float:
        """Where ``ordinal`` lands within the open range, in ``(0, 1)``."""
        return _sigmoid(ordinal / self._scale + self._offset)

    def initial(self, open_rating: float) -> HiddenRating:
        """A newcomer's hidden rating seeded from the open one (``f^-1``)."""
        share = min(max((open_rating - self.settings.rating_min) / self._span, 1e-6), 1.0 - 1e-6)
        mu = self._scale * (math.log(share / (1.0 - share)) - self._offset)
        return HiddenRating(mu, self.settings.sigma_init)

    def projection(self, hidden: HiddenRating) -> float:
        """The hidden rating on the open scale: ``f(o(mu, sigma))``."""
        return self.settings.rating_min + self._span * self._share(hidden.mu / self._ordinal_factor(hidden.sigma))

    def _uncertainty(self, hidden: HiddenRating) -> float:
        """``u = sigma * d f(o) / d mu``: the hidden rating's own spread in open points."""
        factor = self._ordinal_factor(hidden.sigma)
        p = self._share(hidden.mu / factor)
        return max(hidden.sigma * self._span * p * (1.0 - p) / self._scale / factor, 1e-9)

    # --- matchmaking --------------------------------------------------------------

    def effective(self, open_rating: float, hidden: HiddenRating) -> float:
        """The rating teams are balanced on: the open one, corrected by the hidden one."""
        d = self.settings.gate_steepness
        gap = self.projection(hidden) - open_rating
        if self.settings.variant == "reference":
            gate = _sigmoid(2.0 * d * abs(gap) / self._span - d)
        else:
            gate = _sigmoid(d * (abs(gap) / self._uncertainty(hidden) - _GATE_Z_HALF))
        # Between the open rating and the projection by construction, so no clamp.
        return open_rating + gate * gap

    # --- after a match ------------------------------------------------------------

    def rate(self, teams: Sequence[Sequence[HiddenRating]], winner: int | None) -> list[list[HiddenRating]]:
        """New hidden ratings after a two-team match; ``winner`` is 1, 2 or ``None`` (draw)."""
        ranks = [1.0, 2.0] if winner == 1 else [2.0, 1.0] if winner == 2 else [1.0, 1.0]
        rated = self._model.rate(
            [[self._model.rating(mu=h.mu, sigma=h.sigma) for h in team] for team in teams],
            ranks=ranks,
        )
        return [[HiddenRating(r.mu, r.sigma) for r in team] for team in rated]

    def open_delta(self, open_rating: float, old: HiddenRating, new: HiddenRating, outcome: int) -> float:
        """How far one seat's open rating moves; ``outcome`` is +1 won, -1 lost, 0 draw.

        Both variants move the open rating by the match's own impulse on the
        projection plus a pull towards the hidden rating that never exceeds
        that impulse, so the open number only ever moves when its owner plays.
        """
        gap = self.projection(old) - open_rating
        impulse = self.projection(new) - self.projection(old)
        if self.settings.variant == "reference":
            delta = impulse + abs(impulse) * math.tanh(gap / self._span)
        else:
            pull = min(abs(gap), abs(impulse) * math.tanh(abs(gap) / self._uncertainty(old)))
            delta = impulse + math.copysign(pull, gap)
        if outcome > 0:
            delta = max(delta, 0.0)
        elif outcome < 0:
            delta = min(delta, 0.0)
        low = min(open_rating, self.settings.rating_min)
        high = max(open_rating, self.settings.rating_max)
        return min(max(open_rating + delta, low), high) - open_rating
