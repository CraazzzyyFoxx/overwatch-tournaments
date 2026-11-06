"""Structural contract of the team-registration tables.

These are the invariants the design leans on, asserted against the mappers and
against a real SQL engine (SQLite standing in for Postgres) rather than trusted:

* the roster lives on ``registration.registration`` — no slot table — so every
  existing registration reader keeps working unchanged;
* the two partial unique indexes exist and carry their ``WHERE`` clauses, because
  the name index is what makes a silent two-teams-become-one export merge
  impossible, and soft-deleting a team must free its name;
* the mutually referential FKs resolve (``use_alter`` on the captain side);
* an invite stores only the token HASH.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402

import shared.models  # noqa: E402, F401  (registers every mapper)
from shared.models.registration.registration import (  # noqa: E402
    Registration,
    RegistrationEntry,
    RegistrationTeam,
    RegistrationTeamInvite,
)


class MapperContractTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configure_mappers()

    def test_roster_lives_on_the_registration_row(self) -> None:
        """No slot table: a team's roster is a set of ordinary registrations."""
        columns = Registration.__table__.columns
        self.assertIn("registration_team_id", columns)
        self.assertIn("team_slot_code", columns)
        # The bench flag is the participation's: it lives on the registration entry of the team's node.
        self.assertIn("is_substitute", RegistrationEntry.__table__.columns)

    def test_the_new_registration_columns_need_no_backfill(self) -> None:
        """Existing rows must mean "not on a team" without being touched."""
        columns = Registration.__table__.columns
        self.assertTrue(columns["registration_team_id"].nullable)
        self.assertTrue(columns["team_slot_code"].nullable)
        # Not nullable, but server-defaulted — which is equally backfill-free.
        is_substitute = RegistrationEntry.__table__.columns["is_substitute"]
        self.assertFalse(is_substitute.nullable)
        self.assertIsNotNone(is_substitute.server_default)

    def test_team_name_uniqueness_is_partial_on_soft_delete(self) -> None:
        index = next(i for i in RegistrationTeam.__table__.indexes if i.name == "uq_registration_team_name_active")
        self.assertTrue(index.unique)
        self.assertEqual(
            ["tournament_id", "name_normalized"],
            [c.name for c in index.columns],
        )
        # Without the partial WHERE, soft-deleting a team would keep its name
        # reserved forever.
        self.assertEqual(
            "deleted_at IS NULL",
            index.dialect_options["postgresql"]["where"],
        )

    def test_invite_token_index_is_partial_and_unique(self) -> None:
        index = next(
            i for i in RegistrationTeamInvite.__table__.indexes if i.name == "uq_registration_team_invite_token"
        )
        self.assertTrue(index.unique)
        self.assertEqual(["token_sha256"], [c.name for c in index.columns])
        # Targeted invites carry no token; a plain unique index would allow only
        # one of them per table.
        self.assertEqual(
            "token_sha256 IS NOT NULL",
            index.dialect_options["postgresql"]["where"],
        )

    def test_only_the_token_hash_is_stored(self) -> None:
        columns = RegistrationTeamInvite.__table__.columns
        self.assertIn("token_sha256", columns)
        self.assertNotIn("token", columns)
        self.assertEqual(64, columns["token_sha256"].type.length)

    def test_the_circular_captain_fk_uses_alter(self) -> None:
        """``registration.team.captain_registration_id`` <-> ``registration.registration.registration_team_id``."""
        fk = next(fk for fk in RegistrationTeam.__table__.columns["captain_registration_id"].foreign_keys)
        self.assertTrue(fk.use_alter)
        self.assertEqual("fk_registration_team_captain_registration", fk.name)
        self.assertEqual("SET NULL", fk.ondelete)

    def test_deleting_a_team_never_deletes_its_members(self) -> None:
        """A member's registration outlives the team: the FK is SET NULL, and the
        relationship carries no delete cascade. Cascading would silently destroy
        real people's registrations when a captain disbands."""
        fk = next(iter(Registration.__table__.columns["registration_team_id"].foreign_keys))
        self.assertEqual("SET NULL", fk.ondelete)
        self.assertNotIn("delete", RegistrationTeam.members.property.cascade)

    def test_invites_are_owned_by_their_team(self) -> None:
        fk = next(iter(RegistrationTeamInvite.__table__.columns["team_id"].foreign_keys))
        self.assertEqual("CASCADE", fk.ondelete)
        self.assertIn("delete", RegistrationTeam.invites.property.cascade)

    def test_export_link_mirrors_the_draft_team_contract(self) -> None:
        fk = next(iter(RegistrationTeam.__table__.columns["exported_team_id"].foreign_keys))
        self.assertEqual("tournament.team.id", f"{fk.column.table.fullname}.{fk.column.name}")
        self.assertEqual("SET NULL", fk.ondelete)


class DDLTests(TestCase):
    """The FK cycle must be resolvable, and the captain FK must be deferred."""

    def test_the_team_fk_cycle_is_resolvable(self) -> None:
        """SQLAlchemy reports unresolvable cycles as a ``SAWarning`` naming the
        tables involved. The metadata already carries one pre-existing cycle
        (``division_grid``/``division_grid_version``/``workspace``), so asserting
        "no warning" would be asserting someone else's bug; assert instead that
        the team tables are not named in it — that is what ``use_alter`` buys, and
        a regression there breaks every fresh-database bootstrap."""
        import warnings

        from shared.core.db import Base

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tables = Base.metadata.sorted_tables

        cycle_messages = [str(w.message) for w in caught if "cycles" in str(w.message)]
        for message in cycle_messages:
            self.assertNotIn("registration.team", message, message)
            self.assertNotIn("registration.team_invite", message, message)

        names = {t.fullname for t in tables}
        self.assertIn("registration.team", names)
        self.assertIn("registration.team_invite", names)

    def test_captain_fk_is_not_emitted_inline(self) -> None:
        """``use_alter`` moves it to a separate ``ALTER TABLE``; emitting it inside
        ``CREATE TABLE registration.team`` would reference a table that does not
        exist yet."""
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable

        ddl = str(CreateTable(RegistrationTeam.__table__).compile(dialect=postgresql.dialect()))
        self.assertNotIn("fk_registration_team_captain_registration", ddl)
        self.assertIn("captain_registration_id", ddl)
        # The non-circular FKs stay inline.
        self.assertIn("tournament.tournament", ddl)
