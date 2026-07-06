"""Aggregator for all shared SQLAlchemy models.

Importing this package loads every model module, so string-based relationship
resolution and ``configure_mappers()`` keep working against the single shared
``db.Base.metadata``. Every model name importable as ``from shared.models
import X`` before the domain-subpackage split remains importable.
"""
# ruff: noqa: F403

from .achievements import *
from .analytics import *
from .balancer import *
from .catalog import *
from .division_grid import *
from .identity import *
from .ingestion import *
from .matches import *
from .platform import *
from .preferences import *
from .ranks import *
from .registration import *
from .tenancy import *
from .tournament import *
