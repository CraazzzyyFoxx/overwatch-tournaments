"""I/O for team eligibility — ranks, identity keys, Discord membership.

The implementation lives in ``shared.services.team_eligibility`` so the
registered-team export (balancer-service) can reuse the same rules without
importing tournament-service.
"""

from shared.services.team_eligibility import evaluate_team_eligibility

__all__ = ("evaluate_team_eligibility",)
