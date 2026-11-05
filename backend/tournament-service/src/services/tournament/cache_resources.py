"""What each of this service's cached reads embeds, as the resources whose invalidation must miss it.

A read is cached under the current generations of its resources
(``shared.services.cache_generations.versioned``), and every service's ``emit``
of one of them bumps it at commit — a balancer export moves the teams list here
before its reply leaves. Keep a read's tuple in step with what its payload embeds.
"""

from __future__ import annotations

from shared.services.realtime import Resource, resource_generation

__all__ = ("DETAIL", "ENCOUNTERS", "REGISTRATION_LIST", "STANDINGS", "TEAMS", "tournament_generations")

# The tournament read carries its stages, the live participants_count / registrations_count and the flow nodes.
DETAIL = (
    Resource.TOURNAMENT_DETAIL,
    Resource.TOURNAMENT_STAGES,
    Resource.TOURNAMENT_STRUCTURE,
    Resource.TOURNAMENT_FLOW,
    Resource.TOURNAMENT_REGISTRATIONS,
)
ENCOUNTERS = (Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STRUCTURE)
# Standings embed matches_history, built from completed encounters: a score report moves them with no standings row
# written.
STANDINGS = (Resource.TOURNAMENT_STANDINGS, Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STRUCTURE)
TEAMS = (Resource.TOURNAMENT_TEAMS, Resource.TOURNAMENT_STRUCTURE)
# The public participants list. A registration whose `form_version_id` is NULL (the manual/sheet rows of a tournament
# that had no form yet) is rendered against the CURRENT schema's public keys, so a form edit moves it too. The form
# itself is uncached: one reader, and a stale form is a false refusal or a false admission.
REGISTRATION_LIST = (Resource.TOURNAMENT_REGISTRATIONS, Resource.TOURNAMENT_REGISTRATION_FORM)


def tournament_generations(tournament_id: str, resources: tuple[Resource, ...]) -> tuple[str, ...]:
    """``resources``' generations for one tournament; ``tournament_id`` is a template over the cached call
    (``"{params.tournament_id}"``). A call with no tournament (a cross-tournament list) names ``None``, which no
    write bumps: those keys are left to their TTL, as no per-tournament write can know every list it lands in."""
    return tuple(resource_generation(resource, tournament_id) for resource in resources)
