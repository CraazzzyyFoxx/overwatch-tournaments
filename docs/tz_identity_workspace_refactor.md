# ТЗ: Рефакторинг identity/workspace схемы

## Контекст

Репозиторий: `CraazzzyyFoxx/overwatch-tournaments`, ветка `develop`.

Цель — привести модель пользователей и членства в воркспейсе к единой прозрачной схеме:
- **`players.user`** — глобальный identity backbone (один реальный человек, включая теневых игроков из парсера логов/CSV)
- **`workspace_member`** — операционный anchor для всей изолированной доменной логики (RBAC, регистрации, аналитика, достижения)
- **Данные изолированы по воркспейсу по умолчанию**, кросс-воркспейс запрос = явный join через `workspace_member.player_id → players.user`

---

## Часть 1. Схлопывание `auth.user_player`

### Что сейчас
`auth.user_player` — M2M таблица `(auth_user_id, player_id, is_primary)`. Используется как связка "аккаунт → игровой профиль". Фактически инвариант в коде строже: один `player_id` всегда привязан к одному `auth_user_id` (проверка в `PlayerLinkService`). Возможность привязать несколько игроков к одному аккаунту — исторический костыль, от которого избавляемся.

### Что сделать

**1. `shared/models/user.py` — `players.user`**
```python
# Добавить колонку:
auth_user_id: Mapped[int | None] = mapped_column(
    ForeignKey("auth.user.id", ondelete="SET NULL"),
    nullable=True,
    unique=True,   # честная биекция 1:0..1
    index=True,
)
```
`NULL` = теневой игрок (создан парсером логов или CSV-импортом, никогда не логинился).

**2. `shared/models/auth_user.py` — удалить `AuthUserPlayer`**
Удалить класс `AuthUserPlayer` и таблицу `auth.user_player` полностью.

**3. Alembic-миграция**
```sql
-- 1. Добавить колонку
ALTER TABLE players.user ADD COLUMN auth_user_id INT REFERENCES auth.user(id) ON DELETE SET NULL;

-- 2. Перенести данные из auth.user_player
UPDATE players.user pu
SET auth_user_id = up.auth_user_id
FROM auth.user_player up
WHERE up.player_id = pu.id;

-- 3. Добавить unique constraint
CREATE UNIQUE INDEX uq_players_user_auth_user_id
    ON players.user(auth_user_id)
    WHERE auth_user_id IS NOT NULL;

-- 4. Удалить старую таблицу
DROP TABLE auth.user_player;
```

**4. Провижининг при signup**
В `identity-service/src/services/auth_flows.py` и `oauth_flows.py` — после создания `AuthUser` сразу создавать `players.User(name=username_or_email, auth_user_id=auth_user.id)` в той же транзакции. До этого рефакторинга `players.user` создавался лениво только при регистрации на турнир.

**5. Замена использований `AuthUserPlayer` в коде**

| Было | Стало |
|---|---|
| `select(AuthUserPlayer).where(auth_user_id=x)` | `select(User).where(User.auth_user_id == x)` |
| `auth_user.player_links` (relationship) | `auth_user.players` (1-to-many на `players.user`) |
| `PlayerLinkService.link_player(auth_user, player)` | `UPDATE players.user SET auth_user_id=x WHERE id=y` |
| `PlayerLinkService.unlink_player(auth_user, player)` | `UPDATE players.user SET auth_user_id=NULL WHERE id=y` |

Файлы для правки: `identity-service/src/services/player_link_service.py`, `app-service/src/services/admin/user_merge.py`, `app-service/src/services/workspace/service.py`, `shared/rbac/bootstrap.py`, `shared/rpc/identity.py`.

---

## Часть 2. `workspace_member` — новый anchor

### Что сейчас
`workspace_member` хранит `role: str` (денормализованный кэш, рассинхрон с RBAC) и ссылается на `auth.user.id`.

### Что сделать

**1. `shared/models/workspace.py` — `WorkspaceMember`**
```python
class WorkspaceMember(db.TimeStampIntegerMixin):
    __tablename__ = "workspace_member"
    __table_args__ = (
        UniqueConstraint("workspace_id", "player_id", name="uq_workspace_member_workspace_player"),
        UniqueConstraint("id", "workspace_id", name="uq_workspace_member_id_workspace"),  # для composite FK из registration
        {"schema": "workspace"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    # УДАЛИТЬ: role: str
```

**2. Alembic-миграция**
```sql
-- 1. Добавить player_id через auth_user_id → players.user
ALTER TABLE workspace.workspace_member ADD COLUMN player_id INT;

UPDATE workspace.workspace_member wm
SET player_id = pu.id
FROM players.user pu
WHERE pu.auth_user_id = wm.auth_user_id;

-- Если есть workspace_member без players.user (организаторы без игрового профиля)
-- — к этому моменту провижининг при signup уже создал им players.user, так что NULL не будет.
-- Проверка: SELECT COUNT(*) FROM workspace.workspace_member WHERE player_id IS NULL;

ALTER TABLE workspace.workspace_member
    ALTER COLUMN player_id SET NOT NULL,
    ADD CONSTRAINT fk_workspace_member_player FOREIGN KEY (player_id) REFERENCES players.user(id) ON DELETE CASCADE;

CREATE UNIQUE INDEX uq_workspace_member_workspace_player
    ON workspace.workspace_member(workspace_id, player_id);

CREATE UNIQUE INDEX uq_workspace_member_id_workspace
    ON workspace.workspace_member(id, workspace_id);

-- 2. Удалить старые поля
ALTER TABLE workspace.workspace_member
    DROP COLUMN auth_user_id,
    DROP COLUMN role;
```

**3. Системная роль `player`**

В `shared/rbac/catalog.py`:
```python
WORKSPACE_SYSTEM_ROLE_NAMES = {
    ...existing roles...,
    "player": [],   # пустой набор permissions — allow-by-default через capabilities
}
```

**4. Новый permission `registration.self_register`**

В `shared/rbac/catalog.py` добавить в `PERMISSION_CATALOG`:
```python
_permission("registration", "self_register"),
```
Это capability (allow-by-default). Бан конкретного игрока в воркспейсе = запись в `user_permission_deny(auth_user_id, permission_id=<self_register>, workspace_id=<ws_id>)`.

**5. Авто-выдача роли `player` при первой регистрации**

В `tournament-service/src/services/registration/service.py`, функция `create_registration`, до создания `BalancerRegistration`:
```python
# Если workspace_member ещё не существует — создать и выдать роль player
member = await get_or_create_workspace_member(
    session, workspace_id=tournament.workspace_id, player_id=player.id
)
# Проверить capability
if not auth_user.can_capability(tournament.workspace_id, "registration", "self_register"):
    raise HTTPException(status_code=403, detail="Registration is not allowed for this user in this workspace")
```

---

## Часть 3. `UserPermissionDeny` — workspace-scoped deny

### Что сделать

**1. `shared/models/rbac.py`**
```python
class UserPermissionDeny(db.TimeStampIntegerMixin):
    __table_args__ = (
        UniqueConstraint(
            "auth_user_id", "permission_id", "workspace_id",
            name="uq_user_permission_deny_user_perm_workspace"
        ),
        # УДАЛИТЬ старый UniqueConstraint("auth_user_id", "permission_id", ...)
        ...
    )
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
```

**2. `shared/models/auth_user.py` — `has_workspace_permission` / `can_capability`**

Обновить логику deny-проверки: запись с `workspace_id IS NULL` запрещает глобально, с конкретным `workspace_id` — только в нём.

```python
def _is_denied(self, resource: str, action: str, workspace_id: int | None = None) -> bool:
    for deny in self._cached_denies:
        if deny.resource == resource and deny.action == action:
            if deny.workspace_id is None:   # global deny
                return True
            if workspace_id is not None and deny.workspace_id == workspace_id:
                return True
    return False
```

**3. Alembic-миграция**
```sql
ALTER TABLE auth.user_permission_deny ADD COLUMN workspace_id INT
    REFERENCES workspace.id ON DELETE CASCADE;

DROP INDEX IF EXISTS uq_user_permission_deny_user_perm;
CREATE UNIQUE INDEX uq_user_permission_deny_user_perm_workspace
    ON auth.user_permission_deny(auth_user_id, permission_id, COALESCE(workspace_id, 0));
```

---

## Часть 4. `balancer.registration` — переезд на `workspace_member_id`

### Что сделать

**1. `shared/models/balancer.py` — `BalancerRegistration`**
```python
# УДАЛИТЬ:
#   workspace_id (денормализация)
#   auth_user_id

# ДОБАВИТЬ:
workspace_member_id: Mapped[int | None] = mapped_column(
    ForeignKey("workspace.workspace_member.id", ondelete="SET NULL"),
    nullable=True,  # NULL = sheet/CSV import без аккаунта
    index=True,
)

# ОСТАВИТЬ как есть:
user_id: Mapped[int | None] = mapped_column(
    ForeignKey("players.user.id", ondelete="SET NULL"),
    nullable=True,
)
```

**2. Alembic-миграция**
```sql
ALTER TABLE balancer.registration ADD COLUMN workspace_member_id INT
    REFERENCES workspace.workspace_member(id) ON DELETE SET NULL;

-- Заполнить из существующих данных
UPDATE balancer.registration r
SET workspace_member_id = wm.id
FROM workspace.workspace_member wm
JOIN players.user pu ON pu.id = wm.player_id
WHERE pu.auth_user_id = r.auth_user_id
  AND wm.workspace_id = r.workspace_id;

CREATE INDEX ix_balancer_registration_workspace_member_id
    ON balancer.registration(workspace_member_id);

ALTER TABLE balancer.registration
    DROP COLUMN auth_user_id,
    DROP COLUMN workspace_id;
```

**3. Обновить все запросы**

Файлы для правки: `shared/repository/registration.py`, `tournament-service/src/services/registration/service.py`, `tournament-service/src/services/registration/admin.py`, `tournament-service/src/rpc/registration_admin.py`, `tournament-service/src/rpc/public_rpc.py`, `tournament-service/src/core/auth.py`, `balancer-service/src/core/auth.py`, `balancer-service/src/services/admin/balance_analytics.py`.

Паттерн замены в запросах:
- `BalancerRegistration.auth_user_id == x` → `BalancerRegistration.workspace_member.has(WorkspaceMember.player.has(User.auth_user_id == x))`
- `BalancerRegistration.workspace_id == x` → через `tournament_id → Tournament.workspace_id`

---

## Часть 5. `tournament.player` — переезд на `workspace_member_id`

**`shared/models/team.py` — `Player`**
```python
# УДАЛИТЬ: user_id → players.user
# ДОБАВИТЬ:
workspace_member_id: Mapped[int] = mapped_column(
    ForeignKey("workspace.workspace_member.id", ondelete="CASCADE"),
)
```

**Alembic-миграция**
```sql
ALTER TABLE tournament.player ADD COLUMN workspace_member_id INT;

UPDATE tournament.player tp
SET workspace_member_id = wm.id
FROM workspace.workspace_member wm
JOIN tournament.tournament t ON t.id = tp.tournament_id
WHERE wm.workspace_id = t.workspace_id
  AND wm.player_id = tp.user_id;

ALTER TABLE tournament.player
    ALTER COLUMN workspace_member_id SET NOT NULL,
    ADD CONSTRAINT fk_tournament_player_workspace_member
        FOREIGN KEY (workspace_member_id) REFERENCES workspace.workspace_member(id) ON DELETE CASCADE,
    DROP COLUMN user_id;

-- Обновить индексы
DROP INDEX IF EXISTS ix_player_user_tournament;
DROP INDEX IF EXISTS ix_player_team_user;
CREATE INDEX ix_player_workspace_member_tournament ON tournament.player(workspace_member_id, tournament_id);
CREATE INDEX ix_player_team_workspace_member ON tournament.player(team_id, workspace_member_id);
```

---

## Часть 6. Достижения — переезд на `workspace_member_id`

**`shared/models/achievement.py`**

```python
# AchievementEvaluationResult: user_id → workspace_member_id
# AchievementUser: user_id → workspace_member_id
# AchievementOverride: user_id → workspace_member_id
```

**Alembic-миграция** (паттерн одинаковый для всех трёх таблиц):
```sql
ALTER TABLE achievements.evaluation_result ADD COLUMN workspace_member_id INT;

UPDATE achievements.evaluation_result er
SET workspace_member_id = wm.id
FROM workspace.workspace_member wm
WHERE wm.player_id = er.user_id
  AND wm.workspace_id = er.workspace_id;

ALTER TABLE achievements.evaluation_result
    ALTER COLUMN workspace_member_id SET NOT NULL,
    ADD CONSTRAINT fk_eval_result_workspace_member
        FOREIGN KEY (workspace_member_id) REFERENCES workspace.workspace_member(id) ON DELETE CASCADE,
    DROP COLUMN user_id;
```

---

## Порядок выполнения

1. **Часть 1** — схлопывание `auth.user_player` + провижининг `players.user` при signup. Это независимо, можно катить отдельно.
2. **Часть 3** — `UserPermissionDeny.workspace_id`. Независимо, обратно совместимо (nullable добавление).
3. **Часть 2** — `workspace_member` переезжает на `player_id`, удаляется `role`. Зависит от части 1.
4. **Части 4, 5, 6** — переезд на `workspace_member_id`. Зависят от части 2. Можно катить параллельно между собой.

---

## Инварианты для проверки после каждой части

- `SELECT COUNT(*) FROM players.user WHERE auth_user_id IS NOT NULL GROUP BY auth_user_id HAVING COUNT(*) > 1;` → 0 строк (нарушение биекции).
- `SELECT COUNT(*) FROM workspace.workspace_member WHERE player_id IS NULL;` → 0 строк.
- `SELECT COUNT(*) FROM balancer.registration r LEFT JOIN workspace.workspace_member wm ON wm.id = r.workspace_member_id WHERE r.workspace_member_id IS NOT NULL AND wm.id IS NULL;` → 0 строк (нарушение FK).
- `SELECT COUNT(*) FROM tournament.player WHERE workspace_member_id IS NULL;` → 0 строк.

---

## Что НЕ меняется

- `overwatch_rank` / `rank_snapshot` — остаётся на `players.user.id` (факт о battletag, не о membership).
- `social_account` / `social_account_visibility` — без изменений, уже правильно спроектированы.
- `RBAC user_roles` — остаётся на `auth_user_id` (JWT выдаётся на `auth.user`).
- Вся логика `has_workspace_permission` в `AuthUser` — без изменений кроме пункта про deny в части 3.
