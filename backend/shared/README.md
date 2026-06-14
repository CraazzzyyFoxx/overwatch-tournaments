# Shared Library

This library holds the common database models and core components used by every backend service
(`app-service`, `auth-service`, `parser-service`, `tournament-service`, `analytics-service`, and the
rest). It is the **single source of truth** for the ORM layer.

## Structure

```
shared/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── db.py      # Database base classes (Base, TimeStampIntegerMixin, TimeStampUUIDMixin)
│   └── enums.py   # Common enums (HeroClass, LogEventType, LogStatsName, EncounterStatus, MatchEvent, AbilityEvent)
└── models/
    ├── __init__.py
    ├── achievement.py
    ├── analytics.py
    ├── encounter.py
    ├── gamemode.py
    ├── hero.py
    ├── map.py
    ├── match.py
    ├── standings.py
    ├── team.py
    ├── tournament.py
    └── user.py
```

## Usage

Services re-export the shared models and core helpers through their own `src/models` and `src/core`
packages, so application code imports them locally:

```python
from src import models

# Use the shared models
user = models.User(name="example")
tournament = models.Tournament(name="Tournament #1")
```

Base classes and enums are exposed through each service's `src.core`:

```python
from src.core import db, enums

# db.Base, db.TimeStampIntegerMixin are imported from shared
# enums.HeroClass, enums.LogEventType, etc. are imported from shared
```

## Important

- **Do not edit** the per-service `src/models/` files directly — they are proxies for `shared/models/`.
- All database model changes must be made in `shared/models/`.
- Shared enums belong in `shared/core/enums.py`.
- Service-specific enums (for example, `RouteTag`) stay in that service's own `src/core/enums.py`.

## Benefits

1. **Single source of truth** — models are defined in one place.
2. **Consistency** — every service uses identical model definitions.
3. **Easier maintenance** — model changes are made only in `shared`.
4. **Code reuse** — common logic is available to all services.
