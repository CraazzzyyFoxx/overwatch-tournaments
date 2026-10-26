"""Player and account tables have one writer module each — see ``backend/ARCHITECTURE.md`` ("Cross-service data access").

Every service may create players, attach handles and grant workspace roles, but only through the module that owns
the rules for that table: a ``players.user`` row is born in ``UserRepository.create_player`` and linked in
``UserRepository.link_auth_user``; a social account is written by ``SocialIdentityService``; account rows are built
in identity-service; role grants go through ``shared/rbac/bootstrap.py``. A second writer is how those rules drifted
apart before (three name-collision policies, two mirrored avatar columns), and neither the database nor a behaviour
test notices.

ponytail: textual, so it sees ``models.X(`` constructions and ``.auth_user_id =`` assignments, not a generic
``update_fields`` on an owned row; an AST check over typed call sites is the upgrade if that gap ever bites.
"""

from __future__ import annotations

import re

from test_repository_boundaries import BACKEND_ROOT, _iter_python_files

#: rule -> (pattern, owner paths relative to ``backend/``; a trailing ``/`` owns the whole directory).
RULES: dict[str, tuple[re.Pattern[str], tuple[str, ...]]] = {
    "players.user is born in UserRepository.create_player": (
        re.compile(r"\bmodels\.User\(|\binsert\(models\.User\b"),
        ("shared/repository/identity.py",),
    ),
    "players.user.auth_user_id changes in UserRepository.link_auth_user": (
        re.compile(r"\.auth_user_id\s*=(?!=)"),
        ("shared/repository/identity.py",),
    ),
    "social accounts are written by SocialIdentityService": (
        re.compile(r"\bmodels\.SocialAccount(?:Visibility)?\("),
        ("shared/services/social_identity.py",),
    ),
    "account rows are built in identity-service": (
        re.compile(
            r"\bmodels\.(?:AuthUser|OAuthConnection|ApiKey|ApiKeyScope|RefreshToken|Role|Permission|UserPermissionDeny)\("
        ),
        ("identity-service/", "shared/repository/identity.py"),
    ),
    "role grants go through shared/rbac": (
        re.compile(
            r"\b(?:insert|update|delete)\((?:models\.)?user_roles\b|(?i:insert into|delete from)\s+auth\.user_roles"
        ),
        ("shared/rbac/bootstrap.py", "shared/repository/identity.py", "shared/repository/auth_merge.py"),
    ),
}


def _owned(relative: str, owners: tuple[str, ...]) -> bool:
    return any(relative.startswith(owner) if owner.endswith("/") else relative == owner for owner in owners)


def test_identity_tables_are_written_only_by_their_owner_modules() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative.startswith("shared/models/"):
            continue
        text = path.read_text(encoding="utf-8")
        for rule, (pattern, owners) in RULES.items():
            if not _owned(relative, owners) and (match := pattern.search(text)):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{relative}:{line}: {rule}")

    assert offenders == []
