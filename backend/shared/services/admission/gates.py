"""The HTTP projection: ``blockers`` turned into a 400, and nothing else.

This gate makes no decision. It is a PROJECTION of
:attr:`AdmissionEvaluation.blockers`, exactly like the badge and the sort ordinal
are projections of the same structure, and that is the point of the file. Before
this layer, the subscription composition lived in ``subscription_gate`` while the
profile rule was an inline ``if`` in one RPC handler -- two gates in two shapes,
neither aware the other existed, so "what refuses a check-in" could only be
answered by reading two files and hoping there was no third. Deciding here again
would recreate that: the decision belongs to ``evaluate``, once, and every other
surface reads it.

Because it only projects, it also cannot disagree with the badge. A refusal the
server raises and a refusal the client renders now come from the same
:class:`~shared.services.admission.types.RequirementVerdict` list.

**One ``ApiExc`` per blocker, carrying the reason's machine ``code``** (D13, the
convention ``teams.py`` already established and ``lib/registration/team-errors.ts``
already consumes). The code is what lets the client translate a refusal it did
not compute: it never ran the Kleene composition, so without a stable code its
only options are to re-derive the rule -- the duplication this layer deletes -- or
to print the server's Russian verbatim. The ``msg`` is a Russian sentence because
these surfaces are public and Russian-first (§12.2); it is the fallback for a
code the client has no translation for yet, not the primary channel.

Emitting every blocker rather than only the first is deliberate: a player refused
for a closed profile AND an expired subscription would otherwise fix one, retry,
and be refused again for the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.social import PROVIDERS
from shared.services.admission.requirements import open_profile, subscription
from shared.services.admission.types import AdmissionEvaluation, AdmissionStage, RequirementVerdict

if TYPE_CHECKING:
    from shared.services.admission.config import AdmissionConfig
    from shared.services.subscriptions import SubscriptionRequirement

__all__ = ("assert_admitted", "describe_requirement")

#: The gate being refused at, in the genitive the sentences below need. Indexed
#: rather than ``.get``-ed: :class:`AdmissionStage` has two members and both are
#: here, so a miss means a new stage landed without its wording, which is a thing
#: to notice in tests rather than paper over with a blank.
_STAGE_NOUNS: Final[dict[AdmissionStage, str]] = {
    AdmissionStage.registration: "регистрации",
    AdmissionStage.check_in: "чек-ина",
}


def describe_requirement(requirement: SubscriptionRequirement) -> str:
    """Human-readable rule, e.g. ``Boosty уровень 2 или Twitch``.

    The message must name the ACTUAL rule: under ``any`` a patron who satisfies
    one of two providers is admitted, so a generic "subscription required" would
    leave a refused patron unable to tell which side to fix.

    Lives in ``shared`` beside the gate that needs it rather than in
    ``tournament-service``, where it started: a gate importing a service to build
    its own sentence is a dependency pointing the wrong way, and the read schema
    in that service still uses it (``SubscriptionStatusRead.rule``) so it had to
    end up somewhere both can reach.
    """
    parts = []
    for req in requirement.requirements:
        spec = PROVIDERS.get(req.provider)
        label = spec.label if spec is not None else req.provider
        # A threshold of 1 is "any paid tier" — spelling it out reads like a
        # restriction that is not there.
        parts.append(f"{label} уровень {req.min_tier_rank}" if req.min_tier_rank > 1 else label)
    conjunction = " или " if requirement.mode == "any" else " и "
    return conjunction.join(parts)


def _code(verdict: RequirementVerdict) -> str:
    """The machine code for one refusal.

    The first reason, because the reasons are ordered by the resolver and the
    first is the one the player acts on. ``{key}_blocked`` is the fallback for a
    ``blocked`` verdict carrying no reasons at all: that is a resolver bug (see
    ``reason()``'s docstring on the same case), and a 400 with an empty code would
    hand the client nothing to translate while still refusing the player.
    """
    if verdict.reasons:
        return verdict.reasons[0].code
    return f"{verdict.key}_blocked"


def _message(verdict: RequirementVerdict, stage: AdmissionStage, config: AdmissionConfig | None) -> str:
    """The Russian fallback sentence for one refusal.

    Keyed on the GATE stage, not ``verdict.stage``: a requirement armed at
    ``registration`` also blocks check-in, and a patron refused at check-in must
    not read a sign-up message. That distinction used to be encoded by having two
    whole functions.
    """
    if verdict.key == subscription.KEY:
        head = f"Для {_STAGE_NOUNS[stage]} нужна активная подписка"
        rule = config.subscription_rule if config is not None else None
        return f"{head}: {describe_requirement(rule)}." if rule is not None else f"{head}."
    if verdict.key == open_profile.KEY:
        return "Профиль Overwatch должен быть открыт."
    # A registry entry added without wording. Refusing with the raw key beats
    # either a KeyError (a 500 where the player earned a 400) or admitting them.
    return f"Требование не выполнено: {verdict.key}."


def assert_admitted(
    evaluation: AdmissionEvaluation,
    *,
    stage: AdmissionStage,
    config: AdmissionConfig | None = None,
) -> None:
    """Raise 400 iff ``evaluation`` has blockers. Never decides anything itself.

    ``blockers`` already encodes both halves of "does this refuse": only
    ``blocked`` is in it (``undetermined`` fails open, so an outage cannot
    un-admit a subscriber) and only requirements whose gate has arrived. It is
    also empty once the registration is checked in -- D2, check-in spends every
    requirement -- which is what makes an organizer's manual check-in an override
    rather than a state the player is re-refused out of.

    ``config`` is optional and supplies nothing but wording: it is where the
    subscription rule is spelled out for the message. Omitting it costs the rule
    text, never a refusal, so a caller that has no config still gates correctly.
    """
    if not evaluation.blockers:
        return
    raise ApiHTTPException(
        status_code=400,
        detail=[ApiExc(msg=_message(verdict, stage, config), code=_code(verdict)) for verdict in evaluation.blockers],
    )
