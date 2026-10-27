"use client";

import { memo, useDeferredValue, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Search,
  UserPlus,
  Users,
  X,
} from "lucide-react";

import { ICON_BUTTON_CLASS } from "@/components/balancer/balancer-page-helpers";
import { HandleLabel } from "@/components/HandleLabel";
import {
  HandleContextMenuItems,
  HandleCopyButton,
} from "@/app/balancer/components/HandleCopyControls";
import { WorkspacePlayerSheet } from "@/app/balancer/components/WorkspacePlayerSheet";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataPagination } from "@/components/ui/data-pagination";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { notify } from "@/lib/notify";
import { registrationRoles, roleTint, type RoleOntology } from "@/lib/roster/ontology";
import { displaySocialHandle, getSocialProviderConfig } from "@/lib/social/providers";
import { cn } from "@/lib/utils";
import {
  workspacePlayerKeys,
  workspacePlayerService,
  type RosterMember,
} from "@/services/workspace-player.service";
import type { DivisionGrid } from "@/types/workspace.types";
import { Spinner } from "@/components/ui/spinner";

const PER_PAGE = 30;

type WorkspacePlayersSidebarProps = {
  workspaceId: number;
  discipline: string;
  canEdit: boolean;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
};

function memberLabel(member: RosterMember): string {
  return member.display_name || member.identity?.handle || `#${member.member_id}`;
}

type RosterMemberRowProps = {
  member: RosterMember;
  /** The owner game's role dictionary (names, glyphs, tints); `null` while it loads. */
  ontology: RoleOntology | null;
  /** The grid the member's ranks are on: the owner game's grid in the workspace. */
  grid: DivisionGrid;
  /** Opens the rank sheet — the row shows ranks, it no longer edits them. */
  onOpen: (member: RosterMember) => void;
};

/**
 * The tournament pool row, simplified.
 *
 * Same anatomy as `PoolPlayerCompactList`'s row — the ranked-role glyphs
 * beside the name, the division icon and accent-coloured top rank on the
 * right, a handle copy button, and a right-click menu — minus everything
 * that only exists for a tournament registration: the balancer status menu,
 * the pool include/exclude button, and the Flex / Ready / issue chips.
 *
 * Editing opens `WorkspacePlayerSheet` the same three ways the pool row opens
 * the tournament sheet: the name, a double-click, the context menu. The row used
 * to end in three crest pickers instead, which charged every row for a control
 * most rows never use and offered no way to clear a rank at all — that picker
 * listed divisions and nothing else.
 *
 * There is no lineup toggle: this panel is mounted once, by the tournament
 * balancer page, which keeps no per-row selection of its own — a mix picks
 * its lineup through its own dialog (`PickupAddPlayersDialog`) instead.
 *
 * Memoized for the same reason the pool row is: each row mounts a Radix context
 * menu root, and the search field is deferred, so an unmemoized list re-rendered
 * every row on every keystroke.
 */
const RosterMemberRow = memo(function RosterMemberRow({ member, ontology, grid, onOpen }: RosterMemberRowProps) {
  const t = useTranslations("balancerTool.pool");
  const slotLabel = useSlotLabel(ontology);
  const label = memberLabel(member);
  const effective = member.ranks;

  // The owner game's rated roles, in declared order, that the member has a rank for.
  const rankedRoles = registrationRoles(ontology)
    .map((role) => role.code)
    .filter((code) => typeof effective[code] === "number");
  // The strongest role is what a pool decision is made on, and the glyph alone
  // hides the value — same reasoning as the pool row's primary entry.
  const topRank = rankedRoles.reduce<{ role: string; rank: number } | null>((best, role) => {
    const rank = effective[role] as number;
    return best && best.rank >= rank ? best : { role, rank };
  }, null);

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <li
          // `Element`, not `HTMLElement`: a click on an action button's SVG icon
          // has an `SVGElement` target and would fall through to the row.
          onClick={(event) => {
            if (event.target instanceof Element && event.target.closest("[data-card-action]")) {
              return;
            }
            onOpen(member);
          }}
          className={cn(
            "group grid w-full cursor-pointer grid-cols-1 items-start gap-2 rounded-lg border px-2.5 py-2 transition-colors",
            "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]",
            "hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)]",
          )}
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                {rankedRoles.length > 0 ? (
                  <div className="flex shrink-0 items-center gap-1">
                    {rankedRoles.map((role) => (
                      <span key={role} title={slotLabel(role)}>
                        <PlayerRoleIcon role={role} ontology={ontology} size={15} label={slotLabel(role)} />
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="shrink-0 text-label text-[color:var(--aqt-fg-dim)]">{t("noRoles")}</span>
                )}
                <Button
                  type="button"
                  variant="link"
                  size="inline"
                  data-card-action
                  onClick={() => onOpen(member)}
                  title={t("edit", { name: label })}
                  className="min-w-0 justify-start"
                >
                  <HandleLabel handle={label} className="text-caption font-medium text-[color:var(--aqt-fg)]" />
                </Button>
              </div>

              <div className="flex shrink-0 items-center gap-1.5" data-card-action>
                {topRank ? <RankCrest rank={topRank.rank} grid={grid} size={20} /> : null}
                {topRank ? (
                  <span
                    title={t("roster.highestRank", { role: slotLabel(topRank.role), rank: topRank.rank })}
                    className="min-w-10 text-right text-caption font-semibold tabular-nums"
                    style={{ color: roleTint(ontology, topRank.role) }}
                  >
                    {topRank.rank}
                  </span>
                ) : (
                  <span className="text-label text-[color:var(--aqt-fg-dim)]">{t("roster.noRanks")}</span>
                )}
                {member.identity?.handle ? <HandleCopyButton handle={member.identity.handle} /> : null}
              </div>
            </div>
          </div>
        </li>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        <ContextMenuLabel>{t("playerActions")}</ContextMenuLabel>
        <ContextMenuItem onClick={() => onOpen(member)}>
          <Pencil className="h-4 w-4" />
          {t("roster.editRanks")}
        </ContextMenuItem>
        {member.identity?.handle ? <HandleContextMenuItems handles={[member.identity.handle]} /> : null}
      </ContextMenuContent>
    </ContextMenu>
  );
});

export function WorkspacePlayersSidebar({
  workspaceId,
  discipline,
  canEdit,
  collapsed = false,
  onToggleCollapsed,
}: Readonly<WorkspacePlayersSidebarProps>) {
  const t = useTranslations("balancerTool.pool.roster");
  const tCommon = useTranslations("common");
  const queryClient = useQueryClient();
  const metadata = useDisciplineMetadata(workspaceId, discipline);
  const ontology = metadata.data ?? null;
  const grid = useDivisionGrid(discipline);
  const provider = metadata.data?.discipline.identity_provider;
  const identityConfig = provider ? getSocialProviderConfig(provider) : null;
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [handleText, setHandleText] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingMemberId, setEditingMemberId] = useState<number | null>(null);
  const deferredSearch = useDeferredValue(search.trim());
  const searchRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<HTMLInputElement>(null);
  const handleId = useId();
  const handleHintId = `${handleId}-hint`;

  const listParams = { page, perPage: PER_PAGE, query: deferredSearch, discipline };
  const membersQuery = useQuery({
    queryKey: workspacePlayerKeys.list(workspaceId, listParams),
    queryFn: ({ signal }) => workspacePlayerService.list(workspaceId, listParams, { signal }),
  });

  const addPlayer = useMutation({
    mutationFn: (input: { workspaceId: number; discipline: string; identity: { provider: string; handle: string } }) =>
      workspacePlayerService.upsert(input.workspaceId, { discipline: input.discipline, identity: input.identity }),
    onSuccess: async (_member, input) => {
      setHandleText("");
      setIsAddOpen(false);
      notify.success(t("added", { handle: input.identity.handle }));
      await queryClient.invalidateQueries({ queryKey: workspacePlayerKeys.all(input.workspaceId) });
    },
    onError: (error) => notify.apiError(error),
  });

  /**
   * One role per write, so saving Tank never rewrites Damage: the endpoint
   * leaves an omitted role alone, and `clear` deletes the role from the layer
   * instead of pinning a zero over the value it should fall back to.
   */
  const saveRank = useMutation({
    mutationFn: ({ memberId, role, rank }: { memberId: number; role: string; rank: number | null }) =>
      workspacePlayerService.setRanks(workspaceId, memberId, {
        discipline,
        scope: "workspace",
        ranks: rank == null ? {} : { [role]: rank },
        clear: rank == null ? [role] : [],
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacePlayerKeys.all(workspaceId) });
    },
    onError: (error) => notify.apiError(error),
  });

  const pageData = membersQuery.data;
  const total = pageData?.total ?? null;
  const members = pageData?.results ?? [];
  const totalPages = pageData ? Math.max(1, Math.ceil(pageData.total / pageData.per_page)) : 1;
  // Read back out of the list rather than held as state, so a saved rank lands
  // in the open sheet the way the server normalised it.
  const editingMember = members.find((row) => row.member_id === editingMemberId) ?? null;
  /** `1–30 of 224`, using the real page length so the last page is not overstated. */
  const rangeSummary = (perPage: number, shown: number, count: number) => {
    const first = (page - 1) * perPage + 1;
    return t("range", { first, last: first + shown - 1, total: count });
  };

  if (collapsed) {
    return (
      <Card className="flex min-h-0 min-w-0 flex-col items-center gap-3 p-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-expanded={false}
          className={cn(ICON_BUTTON_CLASS, "h-9 w-9")}
          onClick={onToggleCollapsed}
        >
          <PanelRightOpen className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{t("expand")}</span>
        </Button>
        <div className="flex flex-1 flex-col items-center gap-2 pt-1">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-muted)]">
            <Users className="h-4 w-4" aria-hidden="true" />
          </div>
          <Eyebrow
            as="div"
            aria-hidden="true"
            tone="dim"
            className="text-center [writing-mode:vertical-rl]"
          >
            {t("railLabel")}
          </Eyebrow>
        </div>
        {/* `?? 0` used to claim an empty workspace for as long as the first page
            was in flight, and a bare dash announces as "em dash". */}
        {total == null ? (
          <Skeleton className="h-6 w-8 rounded-lg" />
        ) : (
          <div
            title={t("railCount", { count: total })}
            className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-2 py-1 text-label tabular-nums text-[color:var(--aqt-fg-muted)]"
          >
            {total}
            <span className="sr-only"> {t("railUnit", { count: total })}</span>
          </div>
        )}
      </Card>
    );
  }

  const submitHandle = () => {
    if (!provider) return;
    const tag = displaySocialHandle(provider, handleText);
    if (!tag) {
      const { label, placeholder } = getSocialProviderConfig(provider);
      setAddError(t("handleRequired", { provider: label, example: placeholder }));
      handleRef.current?.focus();
      return;
    }
    setAddError(null);
    addPlayer.mutate({ workspaceId, discipline, identity: { provider, handle: tag } });
  };

  const clearSearch = () => {
    setSearch("");
    setPage(1);
    searchRef.current?.focus();
  };

  const listStatus =
    membersQuery.isLoading || total == null
      ? ""
      : total === 0
        ? t("listStatusEmpty")
        : t("listStatus", { range: rangeSummary(PER_PAGE, members.length, total) });

  return (
    // `min-w-0`: as a grid item this panel inherits `min-width: auto`, so below
    // roughly 300px it overflowed its own track instead of truncating rows.
    <Card className="flex min-h-0 min-w-0 flex-col p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          {/* Short enough to hold one line at the narrowest sidebar width; the
              workspace is already the tool's context, and the rail says the same. */}
          <Eyebrow as="div" tone="dim">
            {t("railLabel")}
          </Eyebrow>
          <div className="mt-1 text-sm tabular-nums text-[color:var(--aqt-fg-muted)]">
            {total == null ? (
              <div role="status">
                <span className="sr-only">{t("loading")}</span>
                <Skeleton aria-hidden className="my-0.5 h-4 w-16" />
              </div>
            ) : (
              t("playerCount", { count: total })
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {/* Secondary: adding a tag is rare next to reading and ranking the roster,
              so it lives behind an icon instead of a permanent three-row form. */}
          {canEdit ? (
            <Popover
              open={isAddOpen}
              onOpenChange={(open) => {
                setIsAddOpen(open);
                if (!open) setAddError(null);
              }}
            >
              <PopoverTrigger asChild>
                <Button type="button" variant="ghost" size="icon" className={ICON_BUTTON_CLASS}>
                  <UserPlus className="h-4 w-4" aria-hidden="true" />
                  <span className="sr-only">{t("addTrigger")}</span>
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-64 p-3">
                <form
                  className="space-y-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitHandle();
                  }}
                >
                  <Eyebrow as="label" htmlFor={handleId} tone="dim" className="block">
                    {identityConfig ? t("addBy", { provider: identityConfig.label }) : t("addByGame")}
                  </Eyebrow>
                  <div className="flex gap-1.5">
                    <Input
                      ref={handleRef}
                      id={handleId}
                      value={handleText}
                      onChange={(event) => {
                        setHandleText(event.target.value);
                        if (addError) setAddError(null);
                      }}
                      placeholder={identityConfig?.placeholder ?? ""}
                      autoComplete="off"
                      aria-invalid={addError ? true : undefined}
                      aria-describedby={handleHintId}
                      // `min-w-0`: an `<input>` carries an intrinsic ~170px width that
                      // `min-width: auto` in a flex row turns into a floor.
                      className="min-w-0"
                    />
                    {/* Enabled while empty on purpose: submit validates and points at the field. */}
                    <Button
                      type="submit"
                      className="shrink-0 px-3"
                      disabled={addPlayer.isPending || !provider || !metadata.data?.discipline.enabled}
                    >
                      {addPlayer.isPending ? (
                        <Spinner className="size-3.5" />
                      ) : null}
                      {t("addPlayer")}
                    </Button>
                  </div>
                  <p
                    id={handleHintId}
                    className={cn(
                      "text-label",
                      addError ? "text-rose-200" : "text-[color:var(--aqt-fg-dim)]",
                    )}
                  >
                    {addError ?? t("addHint")}
                  </p>
                </form>
              </PopoverContent>
            </Popover>
          ) : null}
          {onToggleCollapsed ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-expanded
              className={ICON_BUTTON_CLASS}
              onClick={onToggleCollapsed}
            >
              <PanelRightClose className="h-4 w-4" aria-hidden="true" />
              <span className="sr-only">{t("collapse")}</span>
            </Button>
          ) : null}
        </div>
      </div>

      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--aqt-fg-dim)]"
          aria-hidden="true"
        />
        <Input
          ref={searchRef}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchLabel")}
          autoComplete="off"
          className={cn("pl-9", search && "pr-9")}
        />
        {search ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-0.5 top-1/2 h-8 w-8 -translate-y-1/2 rounded-lg text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
            onClick={clearSearch}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="sr-only">{t("clearSearchLabel")}</span>
          </Button>
        ) : null}
      </div>

      {/* The panel is mounted once, by the tournament balancer page, always reading
          and writing the shared workspace canon -- a mix reads/writes its host's own
          book through its own dialog (`PickupAddPlayersDialog`) instead. */}
      <p className="mt-2 text-label leading-tight text-[color:var(--aqt-fg-dim)]">
        {t("scopeCaption")}
      </p>

      <p role="status" aria-live="polite" className="sr-only">
        {listStatus}
      </p>

      {/* `keepPreviousData` keeps the last page on screen when the next one fails.
          Without this strip the panel would silently answer a new query with the
          old rows. */}
      {membersQuery.isError && pageData ? (
        <div
          role="alert"
          className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-2.5 py-1.5 text-label text-rose-100"
        >
          <span className="min-w-0">{t("refreshFailed")}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 shrink-0 rounded border border-rose-300/30 px-1.5 text-rose-100 hover:bg-rose-500/15 hover:text-rose-50"
            onClick={() => void membersQuery.refetch()}
          >
            {tCommon("retry")}
          </Button>
        </div>
      ) : null}

      {/* Below `xl` the balancer shell drops its fixed height, so an uncapped scroller
          would grow to its content and push a scrollbar onto the document. */}
      <div className="mt-3 min-h-0 max-h-[calc(100svh-16rem)] flex-1 overflow-y-auto overflow-x-hidden pr-2">
        {membersQuery.isLoading ? (
          <div className="space-y-1.5">
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <Skeleton key={row} className="h-11 w-full rounded-xl" />
            ))}
          </div>
        ) : membersQuery.isError && !pageData ? (
          <PageStateCard
            state="error"
            title={t("loadFailed")}
            description={t("loadFailedHint")}
            actionLabel={tCommon("retry")}
            onAction={() => void membersQuery.refetch()}
            className="px-4 py-8"
          />
        ) : members.length === 0 ? (
          deferredSearch ? (
            <PageStateCard
              state="filtered-empty"
              title={t("noMatch", { query: deferredSearch })}
              description={t("noMatchHint")}
              actionLabel={t("clearSearch")}
              onAction={clearSearch}
              className="px-4 py-8"
            />
          ) : (
            <PageStateCard
              state="empty"
              title={t("empty")}
              description={canEdit ? t("emptyHintEditor") : t("emptyHintViewer")}
              className="px-4 py-8"
            />
          )
        ) : (
          <ul className="space-y-1.5" aria-label={t("listLabel")}>
            {members.map((member) => (
              <RosterMemberRow
                key={member.member_id}
                ontology={ontology}
                grid={grid}
                member={member}
                onOpen={(row) => setEditingMemberId(row.member_id)}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="mt-2 border-t border-[color:var(--aqt-border)] pt-2">
        <DataPagination
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
          leading={
            pageData
              ? pageData.total === 0
                ? t("playerCount", { count: 0 })
                : rangeSummary(pageData.per_page, members.length, pageData.total)
              : undefined
          }
        />
      </div>

      <WorkspacePlayerSheet
        member={editingMember}
        discipline={discipline}
        ontology={ontology}
        grid={grid}
        canEdit={canEdit}
        // Scoped to the member being written: the sheet is the only surface that
        // edits, so a save anywhere else has no control to disable.
        saving={saveRank.isPending && saveRank.variables?.memberId === editingMemberId}
        onOpenChange={(open) => {
          if (!open) setEditingMemberId(null);
        }}
        onSaveRank={(role, rank) => {
          if (editingMemberId != null) saveRank.mutate({ memberId: editingMemberId, role, rank });
        }}
      />
    </Card>
  );
}
