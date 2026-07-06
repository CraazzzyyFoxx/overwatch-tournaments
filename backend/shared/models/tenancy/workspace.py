from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.division_grid.division_grid import DivisionGridVersion
    from shared.models.identity.user import User

__all__ = (
    "Workspace",
    "WorkspaceMember",
)


class Workspace(db.TimeStampIntegerMixin):
    __tablename__ = "workspace"

    slug: Mapped[str] = mapped_column(String(), unique=True, index=True)
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), server_default="true")
    # Per-workspace site branding (main public site only). Typed hex colours
    # (#RRGGBB); the rest of the palette (text/borders/hover) is derived on the
    # frontend with contrast guards. ``branding_enabled`` is the master toggle so
    # a workspace can turn branding off without losing its saved colours.
    branding_enabled: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    brand_primary: Mapped[str | None] = mapped_column(String(), nullable=True)
    brand_secondary: Mapped[str | None] = mapped_column(String(), nullable=True)
    brand_background: Mapped[str | None] = mapped_column(String(), nullable=True)
    brand_surface: Mapped[str | None] = mapped_column(String(), nullable=True)
    # White-label multi-domain (Phase 1: subdomains). See
    # docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md.
    subdomain: Mapped[str | None] = mapped_column(String(63), unique=True, index=True, nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(), nullable=True)
    # White-label custom domains (Phase 2). Resolver serves the domain only
    # once verified (DNS TXT owner-proof); token is the required TXT value.
    custom_domain: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    custom_domain_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_domain_verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_division_grid_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace", passive_deletes=True)
    default_division_grid_version: Mapped["DivisionGridVersion | None"] = relationship(
        foreign_keys=[default_division_grid_version_id],
        lazy="selectin",
    )


class WorkspaceMember(db.TimeStampIntegerMixin):
    __tablename__ = "workspace_member"

    __table_args__ = (
        UniqueConstraint("workspace_id", "player_id", name="uq_workspace_member_workspace_player"),
        UniqueConstraint("id", "workspace_id", name="uq_workspace_member_id_workspace"),
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"), index=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    player: Mapped["User"] = relationship()
