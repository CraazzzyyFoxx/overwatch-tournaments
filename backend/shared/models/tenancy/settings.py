from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("Settings",)


class Settings(db.TimeStampIntegerMixin):
    """Key-namespaced global settings backed by a JSON blob.

    One row per logical config section (dotted ``key`` such as
    ``parser.rank_collection`` or ``parser.rank_mapping``) so new settings can
    be added without a migration and each section is independently editable and
    cacheable. Lives in the ``public`` schema (no ``__table_args__`` schema),
    matching :class:`shared.models.tenancy.workspace.Workspace`.

    The JSON ``value`` has no DB-level schema — every write is validated against
    a per-key Pydantic model in the admin layer and every read falls back to
    typed defaults.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
