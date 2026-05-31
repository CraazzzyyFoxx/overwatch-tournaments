# Implementation Plan — Top Strong Heroes in Registration Form

## Implementation Status — DONE (2026-05-31)

Implemented on branch `develop`. Verified: backend ruff clean, mappers configure,
31/31 registration tests pass (14 new), single alembic head `reghero0001`; frontend
`tsc --noEmit` + ESLint clean.

**Approved decisions:** scope = public wizard write + read-only display everywhere
(no admin/Google-Sheets write of heroes); picker gated by `built_in_fields.top_heroes`
(`enabled`/`required`/`max_heroes`, default 5); Flex disable shipped now
(`built_in_fields.flex_role.enabled`).

**Notable deviations from the original draft (all corrected against the real code):**
- Migration written as Alembic `op.create_table` (not raw SQL), `down_revision=algonames0001`.
- Public write path is `service.build_registration_roles` (not only admin `replace_registration_roles`); admin write/Sheets left untouched.
- Read field added to `BalancerRegistrationRoleRead` (admin) **and** `RegistrationRoleRead` (public), in **both** tournament-service and balancer-service.
- Hero existence/class validated via a new `shared.hero_catalog.resolve_hero_catalog` threaded into `validate_registration_input` + `build_registration_roles` (mirrors `resolve_subrole_catalog`).
- Flex detection tightened: a submission is flex only when **>1** role and all primary (a lone primary role is not flex). Flex heroes (any class) are replicated onto each of the 3 flex role rows; class checks are skipped for flex.
- Frontend hero pickers live in a dedicated full-width "Top Heroes" section (flex's ~40-hero grid is too cramped inside a half-width card). Pagination envelope is `.results` (not `.items`).

## Overview

Add the ability for players to select their **top strong heroes** per role during tournament registration. Heroes are stored in a normalized junction table (`balancer.registration_role_hero`). The **Flex** role must become configurable — organizers can disable it per tournament via `built_in_fields.flex_role.enabled`.

---

## Open Questions

> [!IMPORTANT]
> **Approve or modify before implementation starts.**
> 1. **Flex hero filter**: For Flex, all heroes of any class are selectable (confirmed). Max 5 heroes.
> 2. **Non-Flex roles**: Also max 5 heroes, filtered by matching `HeroClass` (Tank→Tank, DPS→Damage, Support→Support).
> 3. **`top_heroes` required?**: Should the hero selection be optional (like a sub-role), or required when the feature is enabled? **Assumption: always optional.**
> 4. **`built_in_fields` key name for Flex**: Planning to use `flex_role` (i.e. `built_in_fields.flex_role.enabled = false` disables Flex). Confirm this is acceptable.

---

## Proposed Changes

---

### 1. Database — New Migration

#### [NEW] `migrations/versions/XXX_add_registration_role_hero.py`

Creates a normalized junction table linking registration role entries to heroes, and adds a `top_heroes` flag to `built_in_fields_json` of `BalancerRegistrationForm`.

```sql
-- New table
CREATE TABLE balancer.registration_role_hero (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role_id     BIGINT NOT NULL REFERENCES balancer.registration_role(id) ON DELETE CASCADE,
    hero_id     BIGINT NOT NULL REFERENCES overwatch.hero(id) ON DELETE CASCADE,
    priority    INTEGER NOT NULL,  -- 1 = top pick, 2 = second, etc.
    CONSTRAINT uq_reg_role_hero_role_priority  UNIQUE (role_id, priority),
    CONSTRAINT uq_reg_role_hero_role_hero      UNIQUE (role_id, hero_id)
);
CREATE INDEX ix_balancer_registration_role_hero_role_id
    ON balancer.registration_role_hero (role_id);
```

No data migration needed (table is new).

---

### 2. Backend — Shared Models

#### [MODIFY] [balancer.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/shared/models/balancer.py)

Add `BalancerRegistrationRoleHero` model and update `BalancerRegistrationRole` to include the relationship.

```python
class BalancerRegistrationRoleHero(db.TimeStampIntegerMixin):
    """Ordered hero preference for a registration role entry."""

    __tablename__ = "registration_role_hero"
    __table_args__ = (
        UniqueConstraint("role_id", "priority", name="uq_reg_role_hero_role_priority"),
        UniqueConstraint("role_id", "hero_id",  name="uq_reg_role_hero_role_hero"),
        {"schema": "balancer"},
    )

    role_id:  Mapped[int] = mapped_column(
        ForeignKey("balancer.registration_role.id", ondelete="CASCADE"), index=True
    )
    hero_id:  Mapped[int] = mapped_column(
        ForeignKey("overwatch.hero.id", ondelete="CASCADE")
    )
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    role: Mapped["BalancerRegistrationRole"] = relationship(back_populates="hero_entries")
    hero: Mapped["Hero"] = relationship()
```

In `BalancerRegistrationRole`, add:

```python
hero_entries: Mapped[list["BalancerRegistrationRoleHero"]] = relationship(
    back_populates="role", cascade="all, delete-orphan", order_by="BalancerRegistrationRoleHero.priority"
)
```

Also export `BalancerRegistrationRoleHero` from `__all__`.

---

### 3. Backend — Pydantic Schemas

#### [MODIFY] [registration.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/schemas/registration.py)

**Read path** — add `top_heroes` to `RegistrationRoleRead`:
```python
class RegistrationRoleRead(BaseModel):
    role: str
    subrole: str | None = None
    is_primary: bool = False
    priority: int = 0
    top_heroes: list[str] = Field(default_factory=list)  # ordered hero slugs
```

**Write path** — add `top_heroes` to `RoleWithSubrole`:
```python
class RoleWithSubrole(BaseModel):
    role: str
    subrole: str | None = None
    is_primary: bool = False
    top_heroes: list[str] | None = None  # ordered hero slugs, max 5
```

---

### 4. Backend — Serializers

#### [MODIFY] [serializers.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/services/registration/serializers.py)

When building `RegistrationRoleRead`, also include the ordered hero slugs from `role.hero_entries`:

```python
top_heroes=[entry.hero.slug for entry in sorted(role.hero_entries, key=lambda e: e.priority)]
```

Ensure `hero_entries` is eagerly loaded via `selectinload`.

---

### 5. Backend — Validation

#### [MODIFY] [validation.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/services/registration/validation.py)

Add hero validation inside `validate_registration_input`:

1. **Class check**: for non-Flex roles, each hero must belong to the matching class (`Tank`→`HeroClass.tank`, `dps`→`HeroClass.damage`, `support`→`HeroClass.support`). Flex roles accept any class.
2. **Limit check**: `len(top_heroes) <= 5` (or configurable limit from `built_in_fields.top_heroes.max_heroes`, defaulting to 5).
3. **Existence check**: hero slugs must exist in `overwatch.hero`.

---

### 6. Backend — Registration Use Cases / Service

#### [MODIFY] [admin.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/services/registration/admin.py) / public registration routes

When persisting a registration role:
- After creating/updating `BalancerRegistrationRole`, upsert `BalancerRegistrationRoleHero` rows using the provided `top_heroes` list (delete existing for that role, then bulk-insert).

---

### 7. Backend — Flex Role as `built_in_fields` Key

No new database column needed. The Flex role is controlled by `built_in_fields_json.flex_role`:

```json
{
  "flex_role": { "enabled": false }
}
```

- Default (key absent or `enabled: true`) → Flex is shown.
- `enabled: false` → Flex is hidden from the registration UI and disallowed in the backend.

#### [MODIFY] [registration.py (schemas)](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/schemas/registration.py)

Expose `flex_role_enabled` in `RegistrationFormRead`:

```python
class RegistrationFormRead(BaseModel):
    ...
    flex_role_enabled: bool = True  # derived from built_in_fields.flex_role.enabled
```

OR — simpler approach: the frontend reads `built_in_fields.flex_role?.enabled` directly (consistent with how `primary_role`, `additional_roles`, etc. are read). No new field needed on the schema — just document the convention.

#### [MODIFY] Registration Form admin UI frontend (admin form config)

Add a toggle for `flex_role.enabled` in the balancer registration settings.

---

### 8. Backend — Validation (Flex guard)

#### [MODIFY] [validation.py](file:///c:/Users/andre/Programming/anak-tournaments/backend/tournament-service/src/services/registration/validation.py)

If `built_in_fields.flex_role.enabled == false`, raise `HTTP 422` when any submitted role has `is_primary = true` for all selected roles (i.e., is a full-flex registration).

---

### 9. Frontend — Types

#### [MODIFY] [registration.types.ts](file:///c:/Users/andre/Programming/anak-tournaments/frontend/src/types/registration.types.ts)

```ts
export interface RegistrationRole {
  role: string;
  subrole: string | null;
  is_primary: boolean;
  priority: number;
  top_heroes: string[];   // NEW: ordered hero slugs
}

export interface RoleInput {
  role: string;
  subrole?: string;
  is_primary: boolean;
  top_heroes?: string[]; // NEW
}
```

---

### 10. Frontend — Wizard State

#### [MODIFY] [types.ts](file:///c:/Users/andre/Programming/anak-tournaments/frontend/src/app/(site)/tournaments/[id]/_components/registration/types.ts)

```ts
export type AdditionalRole = {
  code: string;
  subrole: string;
  topHeroes: string[];   // NEW
};

export interface WizardState {
  step: number;
  values: Record<string, string>;
  smurfTags: string[];
  isFlex: boolean;
  primaryRole: string;
  subrole: string;
  primaryRoleHeroes: string[];   // NEW
  additionalRoles: AdditionalRole[];
}

export type WizardAction =
  | ... existing actions ...
  | { type: "SET_PRIMARY_ROLE_HEROES"; heroes: string[] }
  | { type: "SET_ADDITIONAL_ROLE_HEROES"; roleCode: string; heroes: string[] }
  | { type: "SET_FLEX_HEROES"; heroes: string[] }; // for flex mode
```

---

### 11. Frontend — RoleStep Component

#### [MODIFY] [RoleStep.tsx](file:///c:/Users/andre/Programming/anak-tournaments/frontend/src/app/(site)/tournaments/[id]/_components/registration/RoleStep.tsx)

**Flex optional**: Read `form.built_in_fields?.flex_role?.enabled !== false` — if `false`, exclude `"flex"` from `MAIN_ROLE_LAYOUT_ORDER` render.

**Hero picker**: After a role card is selected, render a collapsible `HeroPickerBlock` below the specialization selector (inside `SelectionCard` children). Hero images are loaded via `heroService.getAll({ perPage: -1 })` — fetched once at wizard mount with a `useQuery`.

Props to pass into `RoleStep`:
```ts
primaryRoleHeroes: string[];
onSetPrimaryRoleHeroes: (heroes: string[]) => void;
flexHeroes: string[];     // for flex mode
onSetFlexHeroes: (heroes: string[]) => void;
additionalRoles: AdditionalRole[];  // already includes topHeroes
onSetAdditionalRoles: (roles: AdditionalRole[]) => void;
allHeroes: Hero[];  // passed from wizard
```

---

### 12. Frontend — New `HeroPickerBlock` Component

#### [NEW] `role-step/HeroPickerBlock.tsx`

An inline hero selection grid:

```
Top Heroes (max 5):
┌──────┐ ┌──────┐ ┌──────┐  + more heroes...
│ (1)  │ │ (2)  │ │      │
│ Ana  │ │ Kiri │ │ Bap  │
└──────┘ └──────┘ └──────┘
```

- Heroes are shown filtered by role class (`Tank`, `Damage`, `Support`, or all for Flex).
- Clicking a hero toggles selection; position badge shows rank (1–5).
- Clicking again deselects and reorders.
- Styled with role accent colors.

**Props**:
```ts
interface HeroPickerBlockProps {
  heroes: Hero[];          // pre-filtered to this role's class
  selected: string[];      // slugs in priority order
  max?: number;            // default 5
  roleCode: string;        // for styling
  onChange: (slugs: string[]) => void;
}
```

---

### 13. Frontend — RegistrationWizard

#### [MODIFY] [RegistrationWizard.tsx](file:///c:/Users/andre/Programming/anak-tournaments/frontend/src/app/(site)/tournaments/[id]/_components/registration/RegistrationWizard.tsx)

- Fetch all heroes once on mount with `useQuery`:
  ```ts
  const heroesQuery = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    staleTime: 5 * 60_000,
  });
  ```
- Pass `allHeroes={heroesQuery.data?.items ?? []}` and hero state down to `RoleStep`.
- Update `buildRolesPayload()` to include `top_heroes` per role:
  ```ts
  roles.push({
    role: state.primaryRole,
    subrole: state.subrole || undefined,
    is_primary: true,
    top_heroes: state.primaryRoleHeroes.length > 0 ? state.primaryRoleHeroes : undefined,
  });
  ```

---

### 14. Frontend — Admin Registration Form Settings (Flex toggle)

#### [MODIFY] Admin form config page (formConfig / built-in fields UI)

Add a `flex_role` built-in field toggle (enabled/disabled) in the admin panel so organizers can control Flex role availability per tournament.

---

## Verification Plan

### Automated Tests

- `next lint` to validate frontend types and JSX.

### Manual Verification

1. Open registration wizard for a tournament with `flex_role.enabled = true` (default). Verify Flex card appears.
2. Set `flex_role.enabled = false` in the form config. Verify Flex is gone from the wizard UI and the backend rejects flex registrations.
3. Select a primary role (e.g. Support). Verify only Support heroes appear in the hero picker.
4. Select Flex. Verify all heroes appear.
5. Select up to 5 heroes, confirm ordering badges (1–5) update correctly.
6. Submit registration. Verify network payload includes `top_heroes` per role.
7. Check DB: `SELECT * FROM balancer.registration_role_hero` shows correct entries.
