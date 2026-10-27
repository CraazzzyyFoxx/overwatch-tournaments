"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * The state behind a missing-grid refusal: an organizer gets the way out (create or select a grid of
 * THIS game in THIS workspace, with the game preselected); anyone else gets a plain message — never a link
 * that would bypass the permission it needs. Across communities no workspace grid applies, so that view
 * says so and points at choosing a community instead of at an organizer.
 */
export function MissingGridNotice({
  discipline,
  gameName,
  canManage,
  acrossCommunities = false
}: Readonly<{ discipline: string; gameName: string; canManage: boolean; acrossCommunities?: boolean }>) {
  const t = useTranslations("common.discipline");
  if (acrossCommunities) {
    return (
      <Card role="alert" className="p-3 text-sm">
        <p className="text-muted-foreground">{t("gridMissingAcross", { game: gameName })}</p>
      </Card>
    );
  }
  return (
    <Card role="alert" className="flex flex-col gap-2 p-3 text-sm">
      <p className="text-muted-foreground">{t("gridMissing")}</p>
      {canManage ? (
        <Button asChild variant="link" size="inline" className="self-start whitespace-normal">
          <Link href={`/admin/settings/divisions?discipline=${encodeURIComponent(discipline)}`}>
            {t("gridMissingAction", { game: gameName })}
          </Link>
        </Button>
      ) : (
        <p>{t("gridMissingOrganizer", { game: gameName })}</p>
      )}
    </Card>
  );
}
