"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { Search, EyeOff, LayoutGrid, Table2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { FilterChip } from "@/components/ui/filter-chip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getApiErrorMessage } from "@/lib/api/error";
import { isPhaseWindowActive } from "@/lib/tournament/status";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import registrationService from "@/services/registration.service";
import CheckInSubscriptionProof from "@/components/registration/CheckInSubscriptionProof";
import MyTeamSection from "@/components/registration/MyTeamSection";
import MyInviteOffers from "@/components/registration/MyInviteOffers";
import RegistrationTeamsList from "@/components/registration/RegistrationTeamsList";
import type { Tournament } from "@/types/tournament.types";
import type { RegistrationStatus } from "@/types/registration.types";

import ColumnPicker from "./ColumnPicker";
import { buildParticipantColumns } from "./participantsColumns";
import { useHeroesMap } from "./useHeroesMap";
import ParticipantsPool, { poolDivisionOptions } from "./ParticipantsPool";
import { RegistrationSummary } from "./RegistrationSummary";
import {
  PARTICIPANT_SEARCH_MAX_LENGTH,
  claimCheckInPrompt,
  isMandatoryParticipantColumnId,
  parseStoredParticipantColumnIds,
  participantColumnsStorageKey,
  participantDefaultColumnIds,
  participantResultsScrollTarget,
  participantResultsTransitionSignature,
  readParticipantUrlState,
  shouldScrollParticipantResults,
  subscribeParticipantColumnsStorage,
  updateParticipantUrlState,
  writeStoredParticipantColumnIds,
  type ParticipantUrlUpdate,
  type ParticipantView
} from "./participants-url-state";
import { useParticipantSearchInput } from "./useParticipantSearchInput";
import VirtualParticipantsList from "./VirtualParticipantsList";
import { TournamentParticipantsSkeleton } from "../../_components/TournamentSkeletons";
import { TournamentPageState } from "../../_components/TournamentPageState";
import { ViewSegment } from "../../_components/ViewSegment";
import styles from "../../TournamentDetail.module.css";
import { MyRegistrationCard } from "./MyRegistrationCard";
import {
  ADMIN_ONLY_COLUMN_IDS,
  POOL_TEAM_FORMATIONS,
  STATUS_FILTER_META,
  STATUS_FILTER_ORDER,
  type StatusFilter
} from "../participants.model";

function TournamentParticipantsView({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const { user, status: authStatus } = useAuthProfile();
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsString = searchParams.toString();
  const resultsHeadingRef = useRef<HTMLDivElement>(null);
  const previousResultsSignatureRef = useRef<string | null>(null);
  const [isWithdrawDialogOpen, setIsWithdrawDialogOpen] = useState(false);
  const [isCheckInDialogOpen, setIsCheckInDialogOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  // Stable identity: the row list is memoized, and a fresh callback per render
  // would invalidate it on every parent update.
  const toggleExpanded = useCallback((registrationId: number) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(registrationId)) {
        next.delete(registrationId);
      } else {
        next.add(registrationId);
      }
      return next;
    });
  }, []);

  const isAuthenticated = authStatus === "authenticated" && user !== null;

  const myRegQuery = useQuery({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getMyRegistration(tournament.id),
    enabled: isAuthenticated
  });

  const listQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.listRegistrations(tournament.id)
  });

  const formQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getForm(tournament.id)
  });

  const withdrawMutation = useMutation({
    mutationFn: () => registrationService.withdrawMyRegistration(tournament.id),
    onSuccess: async () => {
      setIsWithdrawDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id)
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id)
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id)
        })
      ]);
    }
  });

  const checkInMutation = useMutation({
    mutationFn: () => registrationService.checkInMyRegistration(tournament.id),
    onSuccess: (updated) => {
      setIsCheckInDialogOpen(false);
      // The response IS the updated registration: write it into the cache
      // instead of refetching. The list refetch is fire-and-forget — our own
      // commit just invalidated the gateway entry, so awaiting it kept the
      // button spinning through the post-invalidation rebuild (and the WS
      // structure_changed event refreshes the list anyway).
      queryClient.setQueryData(
        tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
        updated
      );
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id)
      });
    }
  });

  const registrationList = listQuery.data ?? null;
  // Empty by construction when the organizer hid the list: the server ships no
  // rows, so every filter, column and view below has nothing to operate on and
  // the summary card replaces them.
  const registrations = registrationList?.registrations ?? [];
  const listHidden = registrationList?.hidden === true;
  const myRegistration = myRegQuery.data;
  const form = formQuery.data ?? null;
  const canCheckIn =
    Boolean(myRegistration) &&
    myRegistration?.status === "approved" &&
    myRegistration.checked_in !== true &&
    isPhaseWindowActive(tournament, "check_in");

  // The check-in window is open and this player still has to confirm: open the
  // dialog for them rather than trusting they will find the button. `claimCheckInPrompt`
  // makes it once per tournament per browser.
  useEffect(() => {
    if (!canCheckIn) return;
    if (!claimCheckInPrompt(window.localStorage, tournament.id)) return;
    setIsCheckInDialogOpen(true);
  }, [canCheckIn, tournament.id]);

  const divisionGrid = useDivisionGrid();
  const [needsHeroes, setNeedsHeroes] = useState(false);
  const heroesMap = useHeroesMap({ enabled: needsHeroes });

  // A team column is blank on every row of a solo tournament, so the roster data
  // is what decides whether it belongs in the default set — `RegistrationForm`
  // carries no team-registration flag.
  const hasTeams = useMemo(() => registrations.some((reg) => reg.team != null), [registrations]);

  // Dynamic columns. Built once; the organizer-only columns are dropped from
  // the ROSTER config here, which is the single place the table, the search and
  // the column picker all read — a per-cell blank would still leak the column
  // heading and the filter. The card gets the unfiltered model: those columns
  // are the reader's own answers there.
  const { canAccessPermission } = usePermissions();
  const canReadOrganizerColumns = canAccessPermission("registration.read", tournament.workspace_id);
  const builtColumns = useMemo(
    () => buildParticipantColumns(form, t, divisionGrid, heroesMap, hasTeams),
    [form, t, divisionGrid, heroesMap, hasTeams]
  );
  const allColumns = useMemo(
    () =>
      canReadOrganizerColumns
        ? builtColumns
        : builtColumns.filter((column) => !ADMIN_ONLY_COLUMN_IDS[column.id]),
    [builtColumns, canReadOrganizerColumns]
  );

  // Status counts + chips present in the data.
  const statusCounts = useMemo(() => {
    const counts: Partial<Record<RegistrationStatus, number>> = {};
    for (const reg of registrations) {
      counts[reg.status] = (counts[reg.status] ?? 0) + 1;
    }
    return counts;
  }, [registrations]);

  const presentStatuses = useMemo(() => {
    // Collect all unique statuses actually present in registrations
    const uniqueStatuses = Array.from(new Set(registrations.map((r) => r.status)));

    // Sort them so that built-in ones in STATUS_FILTER_ORDER come first, and any others (custom) come after
    return uniqueStatuses.sort((a, b) => {
      const idxA = STATUS_FILTER_ORDER.indexOf(a);
      const idxB = STATUS_FILTER_ORDER.indexOf(b);

      if (idxA !== -1 && idxB !== -1) {
        return idxA - idxB;
      }
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;

      // Both are custom, sort alphabetically
      return a.localeCompare(b);
    });
  }, [registrations]);
  const allowedStatuses = useMemo(
    () => Array.from(new Set([...STATUS_FILTER_ORDER, ...presentStatuses])),
    [presentStatuses]
  );

  const statusMetaMap = useMemo(() => {
    const map: Record<string, { name: string; dot: string }> = {};
    for (const reg of registrations) {
      if (!map[reg.status]) {
        // Resolve name: prefer status_meta.name, fallback to humanized value
        let name = reg.status_meta?.name ?? reg.status;
        if (name === reg.status) {
          name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
        }

        // Resolve dot color: prefer status_meta.icon_color, fallback to STATUS_FILTER_META, fallback to gray
        let dot = reg.status_meta?.icon_color ?? "";
        if (!dot) {
          dot = STATUS_FILTER_META[reg.status as RegistrationStatus]?.dot ?? "var(--aqt-fg-dim)";
        }

        map[reg.status] = { name, dot };
      }
    }
    return map;
  }, [registrations]);

  const defaultColumnIds = useMemo(() => participantDefaultColumnIds(allColumns), [allColumns]);
  // Optional column ids persisted per tournament. localStorage is an external
  // store: the raw entry is read via useSyncExternalStore (server snapshot is
  // null, so SSR/hydration never touches it) and writers notify subscribers.
  const storedColumnsRaw = useSyncExternalStore(
    subscribeParticipantColumnsStorage,
    () => {
      try {
        return window.localStorage.getItem(participantColumnsStorageKey(tournament.id));
      } catch {
        return null;
      }
    },
    () => null
  );
  const storedColumnIds = useMemo(
    () => parseStoredParticipantColumnIds(storedColumnsRaw),
    [storedColumnsRaw]
  );
  const persistColumns = useCallback(
    (visibleIds: readonly string[]) => {
      writeStoredParticipantColumnIds(
        typeof window === "undefined" ? null : window.localStorage,
        tournament.id,
        visibleIds,
        defaultColumnIds
      );
    },
    [defaultColumnIds, tournament.id]
  );
  const [activeSearchParams, setActiveSearchParams] = useState(searchParamsString);
  useEffect(() => {
    setActiveSearchParams(searchParamsString);
  }, [searchParamsString]);

  // The table is the default everywhere: it answers "is my registration in and
  // what is its state" for every reader, which is what the section is opened
  // for. The by-role pool is the second read, offered only where a pool exists
  // (balancer/draft) — team registration has no pool to show.
  const hasPoolView = POOL_TEAM_FORMATIONS[tournament.team_formation] === true;
  const defaultView: ParticipantView = "table";

  const participantUrl = useMemo(
    () =>
      readParticipantUrlState(
        new URLSearchParams(activeSearchParams),
        allowedStatuses,
        allColumns,
        storedColumnIds,
        defaultView
      ),
    [activeSearchParams, allColumns, allowedStatuses, defaultView, storedColumnIds]
  );
  const latestParamsRef = useRef(searchParamsString);
  const searchQuery = participantUrl.state.search;
  const statusFilter = participantUrl.state.status as StatusFilter;
  const divisionFilter = participantUrl.state.division;
  // `view=pool` in the URL of a team-registration tournament means nothing:
  // that roster has no pool to show.
  const view: ParticipantView = hasPoolView ? participantUrl.state.view : "table";
  const displayedStatuses = useMemo(
    () =>
      statusFilter !== "all" && !presentStatuses.includes(statusFilter)
        ? [...presentStatuses, statusFilter]
        : presentStatuses,
    [presentStatuses, statusFilter]
  );
  const visibleColumnIds = participantUrl.state.visibleColumnIds;
  const visibleColumnIdSet = useMemo(() => new Set(visibleColumnIds), [visibleColumnIds]);
  const visibleColumns = useMemo(
    () => allColumns.filter((column) => visibleColumnIdSet.has(column.id)),
    [allColumns, visibleColumnIdSet]
  );
  const visibility = useMemo(
    () =>
      Object.fromEntries(
        allColumns.map((column) => [column.id, visibleColumnIdSet.has(column.id)])
      ),
    [allColumns, visibleColumnIdSet]
  );

  // The hero catalogue backs the top_heroes cells, every pool row and the
  // reader's own card, so its request stays unsent while none is on screen.
  // Latched on: toggling the column off must not discard a catalogue the user
  // can re-reveal in one click.
  const cardShowsHeroes =
    myRegistration != null && builtColumns.some((column) => column.id === "top_heroes");
  useEffect(() => {
    if (view === "pool" || visibleColumnIdSet.has("top_heroes") || cardShowsHeroes) {
      setNeedsHeroes(true);
    }
  }, [cardShowsHeroes, view, visibleColumnIdSet]);

  useEffect(() => {
    latestParamsRef.current = searchParamsString;
  }, [searchParamsString]);

  const navigateParticipantUrl = useCallback(
    (update: ParticipantUrlUpdate) => {
      const result = updateParticipantUrlState(
        new URLSearchParams(latestParamsRef.current),
        update
      );
      const query = result.params.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      latestParamsRef.current = query;
      setActiveSearchParams(query);
      if (typeof window !== "undefined") {
        if (result.history === "replace") {
          window.history.replaceState(null, "", href);
        } else {
          window.history.pushState(null, "", href);
        }
      }
    },
    [pathname]
  );
  const commitSearch = useCallback(
    (value: string) => navigateParticipantUrl({ type: "search", value }),
    [navigateParticipantUrl]
  );
  const { inputRef: participantSearchInputRef, onChange: handleParticipantSearchChange } =
    useParticipantSearchInput({
      canonicalSearch: searchQuery,
      canonicalUrl: searchParamsString,
      onCommit: commitSearch
    });

  useEffect(() => {
    if (!listQuery.isFetched || !formQuery.isFetched || !participantUrl.needsNormalization) {
      return;
    }
    const query = participantUrl.params.toString();
    const href = query ? `${pathname}?${query}` : pathname;
    latestParamsRef.current = query;
    setActiveSearchParams(query);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", href);
    }
  }, [
    formQuery.isFetched,
    listQuery.isFetched,
    participantUrl.needsNormalization,
    participantUrl.params,
    pathname
  ]);

  const toggleColumn = useCallback(
    (columnId: string) => {
      if (isMandatoryParticipantColumnId(columnId)) return;
      const nextIds = visibleColumnIdSet.has(columnId)
        ? visibleColumnIds.filter((id) => id !== columnId)
        : allColumns
            .filter((column) => column.id === columnId || visibleColumnIdSet.has(column.id))
            .map((column) => column.id);
      persistColumns(nextIds);
      navigateParticipantUrl({
        type: "columns",
        value: nextIds,
        defaultValue: defaultColumnIds
      });
    },
    [
      allColumns,
      defaultColumnIds,
      navigateParticipantUrl,
      persistColumns,
      visibleColumnIdSet,
      visibleColumnIds
    ]
  );
  const resetToDefaults = useCallback(() => {
    persistColumns(defaultColumnIds);
    navigateParticipantUrl({
      type: "columns",
      value: defaultColumnIds,
      defaultValue: defaultColumnIds
    });
  }, [defaultColumnIds, navigateParticipantUrl, persistColumns]);

  // Status filter + dynamic search across all searchable columns.
  const filtered = useMemo(() => {
    const byStatus =
      statusFilter === "all"
        ? registrations
        : registrations.filter((r) => r.status === statusFilter);

    if (!searchQuery.trim()) return byStatus;
    const q = searchQuery.trim().toLowerCase();
    return byStatus.filter((r) =>
      visibleColumns.some((col) => {
        if (!col.searchValue) return false;
        const val = col.searchValue(r);
        return val?.toLowerCase().includes(q) ?? false;
      })
    );
  }, [registrations, searchQuery, statusFilter, visibleColumns]);

  const resultsSignature = useMemo(
    () =>
      participantResultsTransitionSignature({
        search: searchQuery,
        status: statusFilter,
        division: divisionFilter,
        visibleColumnIds
      }),
    [divisionFilter, searchQuery, statusFilter, visibleColumnIds]
  );
  useEffect(() => {
    if (previousResultsSignatureRef.current === null) {
      previousResultsSignatureRef.current = resultsSignature;
      return;
    }
    if (previousResultsSignatureRef.current === resultsSignature) return;
    previousResultsSignatureRef.current = resultsSignature;

    const frame = window.requestAnimationFrame(() => {
      const heading = resultsHeadingRef.current;
      if (!heading) return;
      const headingDocumentTop = heading.getBoundingClientRect().top + window.scrollY;
      const stickyOffset = 112;
      if (
        shouldScrollParticipantResults({
          scrollY: window.scrollY,
          headingDocumentTop,
          stickyOffset
        })
      ) {
        window.scrollTo({
          top: participantResultsScrollTarget(headingDocumentTop, stickyOffset),
          behavior: "auto"
        });
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [resultsSignature]);

  const trueEmpty = listQuery.data !== undefined && registrations.length === 0;
  const filteredEmpty = !trueEmpty && filtered.length === 0;
  const divisionOptions = useMemo(
    () => (view === "pool" ? poolDivisionOptions(registrations, divisionGrid) : []),
    [divisionGrid, registrations, view]
  );

  if (listQuery.isPending && listQuery.data === undefined) {
    return <TournamentParticipantsSkeleton />;
  }

  if (listQuery.isError && listQuery.data === undefined) {
    return <TournamentPageState state="initial-error" onRetry={() => void listQuery.refetch()} />;
  }

  return (
    <div className="space-y-5" data-participant-layout="true">
      {/* My registration status */}
      {myRegistration && (
        <MyRegistrationCard
          registration={myRegistration}
          canCheckIn={canCheckIn}
          onCheckIn={() => setIsCheckInDialogOpen(true)}
          onWithdraw={() => setIsWithdrawDialogOpen(true)}
          isCheckingIn={checkInMutation.isPending}
          isWithdrawing={withdrawMutation.isPending}
          tournament={tournament}
          form={form}
          columns={builtColumns}
        />
      )}

      {/* Team registration lives here rather than behind its own tab. A dedicated
          tab put three sections in one conceptual space (`Teams`, `Participants`,
          `Registered teams`) and duplicated the `Teams` tab outright once the
          organizer exported — both then listed the same teams.

          Both components self-gate and render nothing when they have nothing to
          say, so a solo tournament pays no vertical space. */}
      {tournament.team_formation === "registration" && (
        <>
          <MyInviteOffers tournament={tournament} />
          <MyTeamSection tournament={tournament} />
          <RegistrationTeamsList tournament={tournament} />
        </>
      )}

      <AlertDialog
        open={isCheckInDialogOpen}
        onOpenChange={(open) => {
          setIsCheckInDialogOpen(open);
          // A stale refusal from the previous attempt must not greet the next one:
          // the whole point of the phrase field is that the answer changes.
          if (!open) checkInMutation.reset();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("common.confirmCheckIn")}</AlertDialogTitle>
            <AlertDialogDescription>{t("common.checkInDesc")}</AlertDialogDescription>
          </AlertDialogHeader>
          {/* The subscription requirement is enforced by THIS action, so the last
              manual proof it accepts — the phrase from a subscriber-only post —
              belongs here and nowhere else. */}
          <CheckInSubscriptionProof
            tournamentId={tournament.id}
            requirement={form?.subscription_requirement_json}
            active={isCheckInDialogOpen && form?.require_subscription === true}
          />
          {checkInMutation.isError && (
            <p role="alert" className="text-sm text-[color:var(--aqt-rose)]">
              {getApiErrorMessage(checkInMutation.error, t("common.checkInFailed"))}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={checkInMutation.isPending}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault();
                checkInMutation.mutate();
              }}
              disabled={checkInMutation.isPending}
              className="border border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] bg-[color:var(--aqt-emerald)] text-[color:var(--aqt-bg)] hover:brightness-110"
            >
              {checkInMutation.isPending ? t("common.checkingIn") : t("common.checkIn")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ConfirmDialog
        open={isWithdrawDialogOpen}
        onOpenChange={setIsWithdrawDialogOpen}
        intent={{
          title: t("common.withdrawReg"),
          description: t("common.withdrawDesc"),
          confirmLabel: withdrawMutation.isPending
            ? t("common.withdrawing")
            : t("common.confirmWithdraw"),
          tone: "danger"
        }}
        pending={withdrawMutation.isPending}
        onConfirm={() => withdrawMutation.mutate()}
      />

      {!listHidden && view === "table" && (
        <p aria-atomic="true" aria-live="polite" className="sr-only">
          {t("tournamentDetail.participants.resultCount", { count: filtered.length })}
        </p>
      )}

      {/* One toolbar for both views, two clusters: what you are looking at on
          the left (view switch, status chips), how you are narrowing it on the
          right (search, division, columns). The switch stays put when the view
          changes — `.filter-search` owns the single `auto` margin between the
          clusters, and a second one would scatter the controls across the bar. */}
      {!listHidden && !trueEmpty && (
        <div
          className="filters"
          role="group"
          aria-label={t("common.filters")}
          ref={resultsHeadingRef}
        >
          {hasPoolView && (
            <ViewSegment<ParticipantView>
              param="view"
              defaultValue={defaultView}
              label={t("tournamentDetail.participantsPool.viewLabel")}
              options={[
                {
                  value: "table",
                  label: <Table2 aria-hidden width={14} height={14} />,
                  ariaLabel: t("tournamentDetail.participantsPool.view.table")
                },
                {
                  value: "pool",
                  label: <LayoutGrid aria-hidden width={14} height={14} />,
                  ariaLabel: t("tournamentDetail.participantsPool.view.pool")
                }
              ]}
            />
          )}
          {view === "table" && (
            <>
              <FilterChip
                active={statusFilter === "all"}
                count={registrations.length}
                onClick={() => navigateParticipantUrl({ type: "status", value: "all" })}
              >
                {t("common.all")}
              </FilterChip>
              {displayedStatuses.map((status) => {
                const meta = statusMetaMap[status];
                return (
                  <FilterChip
                    key={status}
                    active={statusFilter === status}
                    count={statusCounts[status] ?? 0}
                    dotColor={meta?.dot ?? "var(--aqt-fg-dim)"}
                    onClick={() =>
                      navigateParticipantUrl({
                        type: "status",
                        value: statusFilter === status ? "all" : status
                      })
                    }
                  >
                    {meta?.name ?? status}
                  </FilterChip>
                );
              })}
            </>
          )}
          <div className="filter-search">
            <Search size={13} aria-hidden />
            <input
              aria-label={
                view === "pool"
                  ? t("tournamentDetail.participantsPool.searchLabel")
                  : t("common.searchParticipants")
              }
              defaultValue={searchQuery}
              maxLength={PARTICIPANT_SEARCH_MAX_LENGTH}
              onChange={handleParticipantSearchChange}
              placeholder={
                view === "pool"
                  ? t("tournamentDetail.participantsPool.searchLabel")
                  : t("common.searchParticipants")
              }
              ref={participantSearchInputRef}
            />
          </div>
          {view === "pool" && divisionOptions.length > 0 && (
            <Select
              value={divisionFilter === null ? "all" : String(divisionFilter)}
              onValueChange={(value) =>
                navigateParticipantUrl({
                  type: "division",
                  value: value === "all" ? null : Number(value)
                })
              }
            >
              <SelectTrigger
                aria-label={t("tournamentDetail.participantsPool.divisionFilterLabel")}
                className="filter-sort h-8 w-[10.5rem] shadow-none focus:ring-0 focus:ring-offset-0"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t("tournamentDetail.participantsPool.allDivisions")}
                </SelectItem>
                {divisionOptions.map((division) => (
                  <SelectItem key={division} value={String(division)}>
                    {t("tournamentDetail.participantsPool.divisionOption", { division })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {view === "table" && (
            <ColumnPicker
              columns={allColumns}
              visibility={visibility}
              onToggle={toggleColumn}
              onReset={resetToDefaults}
            />
          )}
        </div>
      )}

      {/* Participants list — or, when the organizer hid it, the only thing the
          server sent: how many registered and how that field splits by role. */}
      {listHidden ? (
        <section
          aria-label={t("tournamentDetail.participants.hidden.title")}
          className="relative overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 shadow-md backdrop-blur-md sm:p-5"
        >
          <div className="mb-3 flex items-center gap-1.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
            <EyeOff aria-hidden className="size-3.5" />
            {t("tournamentDetail.participants.hidden.title")}
          </div>
          <RegistrationSummary
            total={registrationList?.total ?? 0}
            roleCounts={registrationList?.role_counts ?? {}}
            maxParticipants={registrationList?.max_participants}
          />
          <p className="mt-3 text-caption text-[color:var(--aqt-fg-faint)]">
            {t("tournamentDetail.participants.hidden.description")}
          </p>
        </section>
      ) : view === "pool" ? (
        <ParticipantsPool
          registrations={registrations}
          rosterShape={tournament.roster_shape}
          divisionGrid={divisionGrid}
          heroesMap={heroesMap}
          search={searchQuery}
          division={divisionFilter}
          onResetFilters={() => navigateParticipantUrl({ type: "reset" })}
        />
      ) : filtered.length > 0 ? (
        <VirtualParticipantsList
          allColumns={allColumns}
          expandedIds={expandedIds}
          onToggleExpanded={toggleExpanded}
          registrations={filtered}
          visibleColumns={visibleColumns}
        />
      ) : filteredEmpty ? (
        <TournamentPageState
          state="filtered-empty"
          onReset={() => {
            persistColumns(defaultColumnIds);
            navigateParticipantUrl({ type: "reset" });
          }}
        />
      ) : (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.participants.empty.title")}
          description={t("tournamentDetail.participants.empty.description")}
        />
      )}

      {listQuery.isError && listQuery.data !== undefined ? (
        <div className={styles.refreshMessage} role="alert">
          <span>
            <strong>{t("tournamentDetail.pageState.refreshError.title")}</strong>
            {" — "}
            {t("tournamentDetail.pageState.refreshError.description")}
          </span>
          <button
            className={styles.stateAction}
            onClick={() => void listQuery.refetch()}
            type="button"
          >
            {t("tournamentDetail.pageState.retry")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export { TournamentParticipantsView };
