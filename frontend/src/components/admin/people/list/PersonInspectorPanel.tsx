"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { InspectorField, InspectorSection } from "@/components/kit/InspectorField";
import { SocialAccountList } from "@/components/social/SocialAccountList";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { initials } from "@/lib/utils";
import type { AuthAdminUser } from "@/types/rbac.types";
import type { User } from "@/types/user.types";

import { accessAccountsHref } from "./model";

/** The inspector title already names the person: the body adds what the row cannot. */
export function PersonInspectorPanel({
  person,
  account,
  canReadAuth
}: Readonly<{
  person: User;
  account: AuthAdminUser | undefined;
  canReadAuth: boolean;
}>) {
  const t = useTranslations("adminPeople.people");

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Avatar className="size-12">
          <AvatarImage src={person.avatar_url ?? undefined} alt="" />
          <AvatarFallback>
            {initials(person.name)}
          </AvatarFallback>
        </Avatar>
        <p className="text-sm tabular-nums text-muted-foreground">#{person.id}</p>
      </div>

      {person.social_accounts?.length ? (
        <InspectorSection title={t("socialIdentities")}>
          <SocialAccountList accounts={person.social_accounts} linkify={false} />
        </InspectorSection>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        {canReadAuth ? (
          <InspectorField label={t("columns.account")}>
            {account ? (
              <Link
                className="text-primary underline-offset-4 hover:underline"
                href={accessAccountsHref(person.name)}
              >
                {account.username || account.email}
              </Link>
            ) : (
              <span className="text-muted-foreground">{t("notLinked")}</span>
            )}
          </InspectorField>
        ) : null}
        <InspectorField label={t("stream")}>
          {person.stream_visible === false ? t("hiddenByPlayer") : null}
        </InspectorField>
      </div>
    </div>
  );
}

export function PersonInspectorActions({
  person,
  canEditProfile,
  canMerge,
  onEdit,
  onMerge
}: Readonly<{
  person: User;
  canEditProfile: boolean;
  canMerge: boolean;
  onEdit: (person: User) => void;
  onMerge: (person: User) => void;
}>) {
  const t = useTranslations("adminPeople.people");

  return (
    <>
      {canEditProfile ? (
        <Button variant="outline" size="sm" onClick={() => onEdit(person)}>
          {t("editIdentity")}
        </Button>
      ) : null}
      {canMerge ? (
        <Button variant="outline" size="sm" onClick={() => onMerge(person)}>
          {t("mergeShort")}
        </Button>
      ) : null}
    </>
  );
}
