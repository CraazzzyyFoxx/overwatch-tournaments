"use client";

import { useState, type CSSProperties } from "react";

import { cn, initials } from "@/lib/utils";
import type { Workspace } from "@/types/workspace.types";

/**
 * Deterministic accent for the initials tile, picked by workspace id so a
 * community keeps its colour on every surface. Every `--aqt-*` accent takes
 * `--aqt-bg`-family text, and the tile mixes it into the card, not over it.
 */
const ACCENTS = [
  "var(--aqt-teal)",
  "var(--aqt-blue)",
  "var(--aqt-amber)",
  "var(--aqt-violet)",
  "var(--aqt-emerald)",
  "var(--aqt-rose)"
];

export type WorkspaceAvatarSource = Pick<Workspace, "id" | "name" | "icon_url">;

/**
 * A community's mark: its uploaded icon, else its initials on its accent. The
 * one avatar for communities — header, switcher, cards, footer, notifications.
 * Decorative: the community name always sits next to it.
 */
export function WorkspaceAvatar({
  workspace,
  size,
  className
}: Readonly<{ workspace: WorkspaceAvatarSource; size: number; className?: string }>) {
  // A dead icon URL falls back to the initials instead of a broken image.
  const [failed, setFailed] = useState(false);
  const accent = ACCENTS[Math.abs(workspace.id) % ACCENTS.length];
  const showImage = Boolean(workspace.icon_url) && !failed;

  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden border font-display font-extrabold leading-none tracking-[0.02em]",
        showImage
          ? "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)]"
          : "border-[color:color-mix(in_srgb,var(--ws-accent)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--ws-accent)_14%,var(--aqt-card))] text-[color:var(--ws-accent)]",
        className
      )}
      style={
        {
          "--ws-accent": accent,
          width: size,
          height: size,
          borderRadius: size * 0.25,
          fontSize: size * 0.34
        } as CSSProperties
      }
    >
      {showImage ? (
        // Plain <img>: workspace icons live on arbitrary hosts next/image is not configured for.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={workspace.icon_url ?? undefined}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          className="size-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        initials(workspace.name)
      )}
    </span>
  );
}
