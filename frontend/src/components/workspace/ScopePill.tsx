"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowUpRight, Check, ChevronsUpDown, Gamepad2, Globe, Lock, Plus, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RowButton } from "@/components/ui/row-button";
import { GameMark } from "@/components/workspace/GameMark";
import { useScopePillOpen } from "@/components/workspace/scope-pill-store";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useGameScope } from "@/hooks/useGameScope";
import { ALL_DISCIPLINES, DISCIPLINE_PARAM, pageClassOf, type PillGame } from "@/lib/site/discipline-scope";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { WorkspaceListItem } from "@/types/workspace.types";

type OwnerKind = "tournament" | "match" | "encounter" | "draft" | "scrim" | "mix" | "rule";

/** Which object fixes the game on an owner page, by route (copy `common.discipline.ownerLock.*`). */
const OWNER_KINDS: readonly (readonly [string, OwnerKind])[] = [
  ["/achievements/", "rule"],
  ["/encounters/", "encounter"],
  ["/matches/", "match"],
  ["/draft/", "draft"],
  ["/scrims/", "scrim"],
  ["/balancer/mix/", "mix"]
];

const ownerKindOf = (pathname: string): OwnerKind =>
  OWNER_KINDS.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "tournament";

type MarkSource = Pick<DisciplineDescriptor, "code" | "name" | "short_name" | "icon">;

/** A popover row; `RowButton` rows already bring the reset, full width, focus ring and disabled fade. */
const MENU_ROW_CLASS =
  "flex min-h-10 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-body text-[color:var(--aqt-fg)] " +
  "hover:bg-[color:var(--aqt-overlay-3)] aria-[pressed=true]:bg-[color:var(--aqt-overlay-2)] " +
  "disabled:cursor-not-allowed disabled:hover:bg-transparent";
const MENU_LINK_CLASS = cn(
  MENU_ROW_CLASS,
  "w-full outline-hidden transition-colors focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]"
);
const NOTE_CLASS = "px-2.5 py-1.5 text-caption text-[color:var(--aqt-fg-dim)]";

function SymbolMark({ icon: Icon }: Readonly<{ icon: LucideIcon }>) {
  return (
    <span
      aria-hidden
      className="inline-flex size-6 shrink-0 items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,var(--aqt-card))] text-[color:var(--aqt-teal)]"
    >
      <Icon className="size-3.5" />
    </span>
  );
}

/**
 * The site header's "Community · Game" scope control (spec §3). A community pick keeps it open (the games
 * follow the new area); a game pick closes it. The saved game is never rewritten here except by a game pick.
 * The admin has none: its community switcher is the account menu, its game a per-page filter.
 */
export function ScopePill() {
  const t = useTranslations();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const communitiesId = useId();
  const gamesId = useId();
  const open = useScopePillOpen((state) => state.open);
  const setOpen = useScopePillOpen((state) => state.setOpen);
  const gameBoundParams = useScopePillOpen((state) => state.gameBoundParams);
  const descriptors = useGameDescriptors();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const hostLockedWorkspaceId = useWorkspaceStore((s) => s.hostLockedWorkspaceId);
  const entityWorkspaceId = useWorkspaceStore((s) => s.entityWorkspaceId);
  const entityDiscipline = useWorkspaceStore((s) => s.entityDiscipline);
  const statsScope = useWorkspaceStore((s) => s.statsScope);
  const storedScope = useWorkspaceStore((s) => s.gameScope);
  const setCurrentWorkspace = useWorkspaceStore((s) => s.setCurrentWorkspace);
  const setStatsScope = useWorkspaceStore((s) => s.setStatsScope);
  // The community just picked, shown before the store takes it (see `commit`).
  const [picked, setPicked] = useState<number | "all" | null>(null);

  const routeClass = pageClassOf(pathname);
  // An opened owner (a page, or an editor on a list page) fixes the game wherever the pill shows.
  const pageClass = routeClass !== "platform" && entityDiscipline !== null ? "owner" : routeClass;
  const scope = useGameScope({ pageClass, ownerGame: entityDiscipline });

  useEffect(() => {
    void fetchWorkspaces();
  }, [fetchWorkspaces]);

  const tenant = hostLockedWorkspaceId !== null;
  const pill: PillGame = scope.resolution?.pill ?? { kind: "hidden" };
  const enabledGames = (scope.games ?? []).filter((game) => game.enabled);
  // A tenant's community is the brand: with one game (or none) there is nothing to pick, owner pages included.
  if (routeClass === "platform" || (!tenant && workspaces.length === 0) || (tenant && enabledGames.length <= 1)) {
    return null;
  }

  const markOf = (code: string): MarkSource =>
    descriptors.get(code) ??
    scope.games?.find((game) => game.code === code) ?? { code, name: code, short_name: code, icon: null };
  const scopeGame = scope.resolution && scope.resolution.scope !== ALL_DISCIPLINES ? scope.resolution.scope : null;
  const checked = pill.kind === "game" ? pill.code : pill.kind === "dimmed" ? scopeGame : null;
  const locked = pill.kind === "game" && pill.locked;
  const gamesDisabled = locked || pill.kind === "dimmed";
  const showsGame = pill.kind !== "hidden";
  const gameLabel = checked ? markOf(checked).name : t("common.discipline.all");
  const outOfArea = !gamesDisabled && storedScope !== ALL_DISCIPLINES && scope.resolution?.scope === ALL_DISCIPLINES;

  const pageSlug = /^\/workspace\/([^/]+)/.exec(pathname)?.[1];
  const workspace =
    workspaces.find((w) => w.id === hostLockedWorkspaceId) ??
    (statsScope === "all" ? undefined : workspaces.find((w) => w.id === currentWorkspaceId));
  const allScope = !tenant && statsScope === "all";
  const entityWorkspace =
    workspaces.find((w) => w.id === entityWorkspaceId) ?? workspaces.find((w) => w.slug === pageSlug);
  const communityLabel = workspace?.name ?? t("nav.allWorkspaces");
  const visible = [tenant ? null : communityLabel, showsGame ? gameLabel : null].filter(Boolean).join(" · ");

  // An explicit game the new community does not run would narrow its page to nothing (spec §4.4).
  const dropUnplayedGame = (enabled: readonly string[]) => {
    const explicit = searchParams.get(DISCIPLINE_PARAM);
    if (!explicit || explicit === ALL_DISCIPLINES || enabled.includes(explicit)) return;
    const next = new URLSearchParams(searchParams.toString());
    next.delete(DISCIPLINE_PARAM);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  // A scope write re-renders every scope reader — the whole page — in one blocking pass, and the pill stays open
  // over it. So the pill paints the pick first and the store takes it on the next task.
  // ponytail: the page's own re-render still blocks right after the paint; memoize the heavy pages if that shows.
  const commit = (next: number | "all", apply: () => void) => {
    setPicked(next);
    setTimeout(() => {
      apply();
      setPicked(null);
    });
  };
  const pickWorkspace = (next: WorkspaceListItem) =>
    commit(next.id, () => {
      setCurrentWorkspace(next.id);
      setStatsScope("workspace");
      dropUnplayedGame(next.disciplines_enabled);
    });
  const pickGame = (value: string) => {
    setOpen(false);
    setTimeout(() => scope.selectScope(value, { dropParams: [...gameBoundParams] }));
  };
  const allChecked = picked === null ? allScope : picked === "all";

  return (
    <div className="relative min-w-0">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            // The visible text leads the accessible name (label-in-name).
            aria-label={`${visible} ${t("common.discipline.scopeSuffix")}`}
            className={cn(
              "min-w-0 max-w-[340px] justify-start gap-2 rounded-[9px] pl-1.5 pr-2 [&_svg]:size-3.5",
              "bg-[color:var(--aqt-overlay-1)] data-[state=open]:bg-[color:var(--aqt-overlay-3)]"
            )}
          >
            {tenant ? null : (
              <>
                {workspace ? <WorkspaceAvatar workspace={workspace} size={24} /> : <SymbolMark icon={Globe} />}
                <span className="hidden min-w-0 truncate text-left sm:block">{communityLabel}</span>
              </>
            )}
            {showsGame ? (
              <span
                data-dimmed={pill.kind === "dimmed" || undefined}
                className="flex min-w-0 items-center gap-1.5 data-[dimmed]:opacity-50"
              >
                {tenant ? null : (
                  <span aria-hidden className="hidden text-[color:var(--aqt-fg-faint)] sm:inline">
                    ·
                  </span>
                )}
                {checked ? <GameMark discipline={markOf(checked)} size={24} decorative /> : <SymbolMark icon={Gamepad2} />}
                <span className="hidden min-w-0 truncate text-left sm:block">{gameLabel}</span>
                {locked ? <Lock className="size-3 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden /> : null}
              </span>
            ) : null}
            <ChevronsUpDown className="size-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          sideOffset={8}
          collisionPadding={12}
          aria-label={t("nav.viewingScope")}
          className={cn(
            "w-[280px] max-w-[calc(100vw-24px)] p-1.5",
            !tenant && showsGame && "sm:w-[540px]"
          )}
        >
          <div className={cn("grid gap-1.5", !tenant && showsGame && "sm:grid-cols-2")}>
            {tenant ? null : (
              <div role="group" aria-labelledby={communitiesId}>
                <Eyebrow as="p" id={communitiesId} className="px-2.5 pb-1.5 pt-2">
                  {t("nav.workspaces")}
                </Eyebrow>
                <RowButton
                  onClick={() => commit("all", () => setStatsScope("all"))}
                  aria-pressed={allChecked}
                  className={MENU_ROW_CLASS}
                >
                  <SymbolMark icon={Globe} />
                  <span className="min-w-0 flex-1 truncate">{t("nav.allWorkspaces")}</span>
                  {allChecked ? <Check className="size-4 shrink-0" aria-hidden /> : null}
                </RowButton>
                {workspaces.map((item) => {
                  const isCurrent = picked === null ? item.id === workspace?.id : item.id === picked;
                  // The address shown to people: a verified custom domain only.
                  const host = item.custom_domain && item.custom_domain_verified_at ? item.custom_domain : null;
                  return (
                    <RowButton
                      key={item.id}
                      onClick={() => pickWorkspace(item)}
                      aria-pressed={isCurrent}
                      className={MENU_ROW_CLASS}
                    >
                      <WorkspaceAvatar workspace={item} size={24} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{item.name}</span>
                        {host ? (
                          <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">{host}</span>
                        ) : null}
                      </span>
                      {isCurrent ? <Check className="size-4 shrink-0" aria-hidden /> : null}
                    </RowButton>
                  );
                })}
                {entityWorkspace ? (
                  <p className={NOTE_CLASS}>{t("nav.entityCommunity", { name: entityWorkspace.name })}</p>
                ) : null}
              </div>
            )}
            {showsGame ? (
              <div role="group" aria-labelledby={gamesId}>
                <Eyebrow as="p" id={gamesId} className="px-2.5 pb-1.5 pt-2">
                  {t("common.discipline.select")}
                </Eyebrow>
                <RowButton
                  disabled={gamesDisabled}
                  onClick={() => pickGame(ALL_DISCIPLINES)}
                  aria-pressed={checked === null}
                  className={MENU_ROW_CLASS}
                >
                  <SymbolMark icon={Gamepad2} />
                  <span className="min-w-0 flex-1 truncate">{t("common.discipline.all")}</span>
                  {checked === null ? <Check className="size-4 shrink-0" aria-hidden /> : null}
                </RowButton>
                {enabledGames.map((item) => (
                  <RowButton
                    key={item.code}
                    disabled={gamesDisabled}
                    onClick={() => pickGame(item.code)}
                    aria-pressed={checked === item.code}
                    className={MENU_ROW_CLASS}
                  >
                    <GameMark discipline={item} size={24} decorative />
                    <span className="min-w-0 flex-1 truncate">{item.name}</span>
                    {checked === item.code ? <Check className="size-4 shrink-0" aria-hidden /> : null}
                  </RowButton>
                ))}
                {locked && checked ? (
                  <p className={NOTE_CLASS}>
                    {t(`common.discipline.ownerLock.${ownerKindOf(pathname)}`, { game: markOf(checked).name })}
                  </p>
                ) : null}
                {pageClass === "none" ? <p className={NOTE_CLASS}>{t("common.discipline.noneNote")}</p> : null}
                {outOfArea ? (
                  <p className={NOTE_CLASS}>{t("common.discipline.areaNote", { game: markOf(storedScope).name })}</p>
                ) : null}
              </div>
            ) : null}
          </div>
          {tenant ? null : (
            <>
              <div className="my-1.5 h-px bg-[color:var(--aqt-border)]" />
              {workspace ? (
                <Link
                  href={`/workspace/${workspace.slug}`}
                  prefetch={false}
                  onClick={() => setOpen(false)}
                  className={MENU_LINK_CLASS}
                >
                  <ArrowUpRight className="size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">{t("nav.openWorkspace")}</span>
                </Link>
              ) : null}
              <Link
                href="/get-workspace"
                onClick={() => setOpen(false)}
                className={cn(MENU_LINK_CLASS, "text-[color:var(--aqt-fg-muted)]")}
              >
                <Plus className="size-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{t("nav.createWorkspace")}</span>
              </Link>
            </>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
