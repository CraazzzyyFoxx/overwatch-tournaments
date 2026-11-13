"use client";

import { RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadMatchUI } from "@/disciplines/registry/match";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import type { MatchWithUserStats } from "@/types/user.types";

/**
 * The viewer's per-match badge on a profile row (a game's placement chip), drawn by the match's own game's
 * `matchRowBadge` module slot. A match the viewer was not observed in has none, and a game whose module has no
 * badge draws nothing; but the game's metadata is a required read, so while it loads the row holds a
 * placeholder and when it fails the badge says so and offers a retry — never a silent absence. Rendered inside
 * a `TooltipProvider`; the row it sits in may be a link or a click target, so the retry stops both.
 */
export default function MatchRowBadge({ match }: Readonly<{ match: MatchWithUserStats }>) {
  const t = useTranslations();
  const metadata = useDisciplineMetadata(match.workspace_id, match.discipline);
  if (!match.viewer) return null;
  if (metadata.isPending) return <Skeleton aria-hidden className="h-4 w-6 rounded" />;
  if (metadata.isError) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        title={t("matches.native.badgeError")}
        aria-label={`${t("matches.native.badgeError")} ${t("common.retry")}`}
        disabled={metadata.isFetching}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void metadata.refetch();
        }}
        className="text-[color:var(--aqt-rose)] hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-rose)]"
      >
        <RotateCw aria-hidden />
      </Button>
    );
  }
  return (
    <DisciplineWidget
      discipline={match.discipline}
      load={loadMatchUI}
      slot="matchRowBadge"
      capabilities={metadata.data.discipline.capabilities}
      props={{ match, metadata: metadata.data }}
      fallback={null}
    />
  );
}
