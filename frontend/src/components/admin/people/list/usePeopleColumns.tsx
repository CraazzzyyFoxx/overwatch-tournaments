"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRightLeft, Pencil, Trash2, UserCog } from "lucide-react";

import { columnMeta, createKebabColumn } from "@/components/data-table";
import { SocialAccountList } from "./SocialAccountList";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { initials } from "@/lib/utils";
import type { AuthAdminUser } from "@/types/rbac.types";
import type { User } from "@/types/user.types";

import { accessAccountsHref } from "./model";

export function usePeopleColumns({
  canReadAuth,
  canEditProfile,
  canMerge,
  canDelete,
  authByPlayerId,
  onEdit,
  onMerge,
  onDelete
}: Readonly<{
  canReadAuth: boolean;
  canEditProfile: boolean;
  canMerge: boolean;
  canDelete: boolean;
  authByPlayerId: ReadonlyMap<number, AuthAdminUser>;
  onEdit: (person: User) => void;
  onMerge: (person: User) => void;
  onDelete: (person: User) => void;
}>): ColumnDef<User>[] {
  const t = useTranslations("adminPeople.people");

  return useMemo<ColumnDef<User>[]>(
    () => [
      {
        accessorKey: "name",
        header: t("columns.person"),
        meta: columnMeta<User>({
          sticky: true,
          searchValue: (person) => `${person.name} ${person.id}`
        }),
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-2.5">
            <Avatar className="size-7">
              <AvatarImage src={row.original.avatar_url ?? undefined} alt="" />
              <AvatarFallback>
                {initials(row.original.name)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <Link
                href={`/admin/people/${row.original.id}`}
                className="block truncate font-medium text-foreground underline-offset-2 hover:underline"
              >
                {row.original.name}
              </Link>
              <p className="font-mono text-xs tabular-nums text-muted-foreground">
                #{row.original.id}
              </p>
            </div>
          </div>
        )
      },
      {
        id: "identities",
        header: t("columns.identities"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.social_accounts?.length ? (
            <SocialAccountList accounts={row.original.social_accounts} />
          ) : null
      },
      // Without the global auth grant there is nothing to read, so no column
      // rather than a column of blanks claiming every identity is unlinked.
      ...(canReadAuth
        ? [
            {
              id: "account",
              header: t("columns.account"),
              enableSorting: false,
              cell: ({ row }) => {
                const account = authByPlayerId.get(row.original.id);
                if (!account) {
                  return <span className="text-sm text-muted-foreground">{t("notLinked")}</span>;
                }
                return (
                  <span className="truncate text-sm" title={account.email}>
                    {account.username || account.email}
                  </span>
                );
              }
            } satisfies ColumnDef<User>
          ]
        : []),
      createKebabColumn<User>(
        (person) => [
          { label: t("actions.openPerson"), href: `/admin/people/${person.id}` },
          {
            label: t("actions.edit"),
            icon: Pencil,
            hidden: !canEditProfile,
            onSelect: () => onEdit(person)
          },
          {
            label: t("actions.access"),
            icon: UserCog,
            hidden: !canReadAuth,
            href: accessAccountsHref(person.name)
          },
          {
            label: t("actions.merge"),
            icon: ArrowRightLeft,
            hidden: !canMerge,
            onSelect: () => onMerge(person)
          },
          {
            label: t("actions.delete"),
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => onDelete(person)
          }
        ],
        { rowLabel: (person) => person.name }
      )
    ],
    [t, canReadAuth, canEditProfile, canMerge, canDelete, authByPlayerId, onEdit, onMerge, onDelete]
  );
}
