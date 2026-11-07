"use client";

import { useEffect, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import type { LinkTabItem } from "@/components/kit/LinkTabs";
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { useHubStagesQuery } from "../hubQueries";
import { SubTabShell, useSubTabSegment } from "../sub-tabs";
import { allowedBracketSubTab, BRACKET_SUB_TABS, type BracketSubTab } from "../tab-guards";

const DEFAULT_SUB_TAB: BracketSubTab = BRACKET_SUB_TABS[0];

/**
 * Sub-tab bar of the Bracket hub tab: Stages · Lobbies · Flow.
 *
 * Navigation only. `Stages` is the bare `/bracket` container, so every link
 * that already points there keeps landing on the stage editor. `?stage=` rides
 * along on a switch to Stages or Lobbies, so the editor's selected stage
 * survives it; Flow selects by its own `?node=`.
 *
 * A duel tournament has no lobby, which leaves `Stages` and `Flow`.
 */
export default function BracketLayout({ children }: Readonly<{ children: ReactNode }>) {
  const t = useTranslations("adminBracket.layout");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const searchParams = useSearchParams();
  const router = useRouter();

  const basePath = `/admin/tournaments/${tournamentId}/bracket`;
  const { active } = useSubTabSegment(basePath, BRACKET_SUB_TABS, DEFAULT_SUB_TAB);

  // The Lobbies view exists only where there is a lobby: an FFA stage. The
  // stages are the hub's own query, so asking costs no extra request.
  const stagesQuery = useHubStagesQuery(tournamentId);
  const hasFfaStage = (stagesQuery.data ?? []).some((stage) =>
    FFA_STAGE_TYPES.includes(stage.stage_type)
  );
  // `hasFfaStage` is false until the stages are in, so the Lobbies page never
  // mounts against a duel tournament, not even for the paint before the bounce.
  const activeAllowed = allowedBracketSubTab(active, { hasFfaStage });

  // The URL itself is corrected only once the stages are in: bouncing on the
  // first paint would kick an organizer off the view they linked to.
  useEffect(() => {
    if (!stagesQuery.data || activeAllowed) return;
    router.replace(basePath);
  }, [stagesQuery.data, activeAllowed, basePath, router]);

  const stage = searchParams.get("stage");
  const scopeQuery = stage ? `?stage=${encodeURIComponent(stage)}` : "";

  const items: LinkTabItem[] = BRACKET_SUB_TABS.map((key) => ({
    key,
    label: t(key),
    href: `${key === DEFAULT_SUB_TAB ? basePath : `${basePath}/${key}`}${key === "flow" ? "" : scopeQuery}`,
    hidden: !allowedBracketSubTab(key, { hasFfaStage })
  }));

  return (
    <SubTabShell items={items} activeKey={active} ariaLabel={t("views")} allowed={activeAllowed}>
      {children}
    </SubTabShell>
  );
}
