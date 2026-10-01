"use client";

import { useEffect, type ReactNode } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { useHubStagesQuery } from "../hubQueries";
import { allowedBracketSubTab, BRACKET_SUB_TABS, type BracketSubTab } from "../tab-guards";

const SUB_TAB_LABELS: Record<BracketSubTab, string> = {
  stages: "Stages",
  lobbies: "Lobbies"
};

const DEFAULT_SUB_TAB: BracketSubTab = BRACKET_SUB_TABS[0];

function isBracketSubTab(value: string): value is BracketSubTab {
  return (BRACKET_SUB_TABS as readonly string[]).includes(value);
}

/**
 * Sub-tab bar of the Bracket hub tab: Stages · Lobbies.
 *
 * Navigation only. `Stages` is the bare `/bracket` container, so every link
 * that already points there keeps landing on the stage editor. `?stage=` rides
 * along on a switch, so the editor's selected stage survives it.
 *
 * A duel tournament has no lobby, which leaves `Stages` alone: a bar of one
 * tab is a label pretending to be navigation, so it is not drawn at all.
 */
export default function BracketLayout({ children }: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();

  const basePath = `/admin/tournaments/${tournamentId}/bracket`;
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? DEFAULT_SUB_TAB)
    : DEFAULT_SUB_TAB;
  const active: BracketSubTab = isBracketSubTab(segment) ? segment : DEFAULT_SUB_TAB;

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
    label: SUB_TAB_LABELS[key],
    href: `${key === DEFAULT_SUB_TAB ? basePath : `${basePath}/${key}`}${scopeQuery}`,
    hidden: !allowedBracketSubTab(key, { hasFfaStage })
  }));

  return (
    <div className="space-y-4">
      {items.filter((item) => !item.hidden).length > 1 ? (
        <LinkTabs items={items} activeKey={active} level={2} ariaLabel="Bracket views" />
      ) : null}
      {activeAllowed ? children : null}
    </div>
  );
}
