"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Archive,
  ArrowUpToLine,
  ExternalLink,
  Pencil,
  RotateCcw,
  Trash2
} from "lucide-react";

import { columnMeta, createKebabColumn } from "@craazzzyyfoxx/admin-kit/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import type { TournamentLink } from "@/types/stream.types";
import { primaryStreamLinkSortOrder } from "../tournamentLinks.helpers";

/** Callbacks must keep a stable identity, or the column memo rebuilds every render. */
export function useLinkColumns({
  links,
  canUpdate,
  canDelete,
  onMakePrimary,
  onEdit,
  onArchive,
  onRestore
}: Readonly<{
  /** Every row, sorted — "make primary" is relative to the other broadcasts. */
  links: TournamentLink[];
  canUpdate: boolean;
  canDelete: boolean;
  onMakePrimary: (input: { id: number; sortOrder: number }) => void;
  onEdit: (link: TournamentLink) => void;
  onArchive: (link: TournamentLink) => void;
  onRestore: (id: number) => void;
}>): ColumnDef<TournamentLink>[] {
  const t = useTranslations("adminTournament.links");
  return useMemo<ColumnDef<TournamentLink>[]>(
    () => [
      {
        accessorKey: "kind",
        header: t("kind"),
        size: 112,
        cell: ({ row }) => t(`kinds.${row.original.kind}`),
        meta: columnMeta<TournamentLink>({
          searchValue: (link) => t(`kinds.${link.kind}`)
        })
      },
      {
        accessorKey: "label",
        header: t("label"),
        cell: ({ row }) => row.original.label,
        meta: columnMeta<TournamentLink>({ className: "max-w-[16rem] truncate" })
      },
      {
        accessorKey: "url",
        header: t("url"),
        cell: ({ row }) => (
          <a
            href={row.original.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex max-w-full items-center gap-1 truncate text-primary underline-offset-4 hover:underline"
          >
            <span className="truncate">{row.original.url}</span>
            <ExternalLink aria-hidden className="size-3.5 shrink-0" />
          </a>
        ),
        meta: columnMeta<TournamentLink>({ className: "max-w-[22rem]" })
      },
      {
        // ponytail: sort order is a plain number field in the edit dialog, not
        // per-row up/down arrows — no other admin list in this project reorders
        // inline, and a handful of links does not justify inventing the pattern.
        // If these lists ever grow past a screenful, lift the arrow + reindex
        // handling from `StageManager`.
        accessorKey: "sort_order",
        header: t("order"),
        size: 80,
        meta: columnMeta<TournamentLink>({ align: "right", numeric: true })
      },
      {
        // Active is the norm, so only the exception is marked.
        id: "state",
        header: t("state"),
        size: 96,
        enableSorting: false,
        meta: columnMeta<TournamentLink>({ align: "center" }),
        cell: ({ row }) =>
          row.original.is_active ? null : (
            <StatusIcon icon={Archive} label={t("archived")} variant="muted" />
          )
      },
      createKebabColumn<TournamentLink>(
        (link) => {
          // Absent, not disabled, on rows that cannot be promoted — the same
          // choice the archive/restore pair makes. `primaryStreamLinkSortOrder`
          // is null for non-broadcasts, archived rows and the link that already
          // leads the order, and otherwise IS the number to send.
          const primarySortOrder = primaryStreamLinkSortOrder(link, links);
          return [
            {
              label: t("makePrimary"),
              icon: ArrowUpToLine,
              hidden: !canUpdate || primarySortOrder === null,
              onSelect: () =>
                primarySortOrder !== null &&
                onMakePrimary({ id: link.id, sortOrder: primarySortOrder })
            },
            { label: t("edit"), icon: Pencil, hidden: !canUpdate, onSelect: () => onEdit(link) },
            {
              label: t("archive"),
              icon: Trash2,
              destructive: true,
              hidden: !canDelete || !link.is_active,
              onSelect: () => onArchive(link)
            },
            {
              label: t("restore"),
              icon: RotateCcw,
              hidden: !canUpdate || link.is_active,
              onSelect: () => onRestore(link.id)
            }
          ];
        },
        { rowLabel: (link) => link.label ?? link.url }
      )
    ],
    [t, links, canUpdate, canDelete, onMakePrimary, onEdit, onArchive, onRestore]
  );
}
