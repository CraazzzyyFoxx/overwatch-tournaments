"""Shared stand-in for ``SubscriptionResolver.load_requirement``.

Four suites -- the check-in gate, the registration gate, the participants list and the
patron's own status read -- each need a fake resolver that turns a raw rule blob into
what the real resolver would hand back. Every one of them used to carry its own copy of
that parse-and-fail-open logic, which meant the contract was defined FIVE times: once
in ``shared.services.subscriptions.entitlements.SubscriptionResolver.load_requirement``
and once per suite. All four suites would therefore have stayed green if the real
contract regressed, which is exactly backwards for a chokepoint the whole admission
stack trusts.

One definition, imported everywhere. It must keep tracking the real
``load_requirement``: same caught exception set (see ``resolver_rule`` below), same
empty-collapse. The behaviour itself is unit-tested against the real resolver in
``shared/tests/test_subscription_load_requirement.py``; this module exists so the gate
suites can stay focused on their own decision tables rather than re-testing the parse.

Only the helper is shared. The fake resolvers stay in their own suites: each gate asks
the resolver different questions, and merging them would trade four honest fakes for
one that has to be configured into four shapes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Same bootstrap the suites use, so this module is importable on its own rather than
# only after whichever test happened to be collected first patched `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.services.subscriptions import SubscriptionRequirement, parse_requirement  # noqa: E402


def resolver_rule(blob: dict | None) -> SubscriptionRequirement | None:
    """What the real resolver would hand back for ``blob``.

    Mirrors ``SubscriptionResolver.load_requirement``: fails OPEN on anything
    ``parse_requirement`` chokes on, and collapses an empty rule to ``None`` so
    "toggle on, nothing configured" stays the documented no-op that never calls a
    provider.

    The caught set matches the real chokepoint exactly and must keep doing so.
    ``parse_requirement`` only documents ``ValueError`` (unknown ``mode``), but the blob
    is arbitrary stored JSON whose shape nothing validates on write:
    ``{"requirements": "boosty"}`` raises ``AttributeError`` and
    ``{"requirements": 5}`` raises ``TypeError``. A narrower set here would let these
    suites pass while the production path 500s.
    """
    try:
        requirement = parse_requirement(blob)
    except ValueError, TypeError, AttributeError:
        return None
    return requirement if requirement.requirements else None
