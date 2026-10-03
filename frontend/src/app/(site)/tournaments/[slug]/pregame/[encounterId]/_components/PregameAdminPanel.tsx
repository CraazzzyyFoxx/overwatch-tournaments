"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";
import type { PickBanSide } from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";

import { PregameAdminControls } from "./PregameAdminControls";
import { PregameRoomHistory } from "./PregameRoomHistory";
import type { PickBanAdminSlot } from "./PickBanPanel";

const KINDS: readonly PickBanKind[] = ["map", "hero"];

/**
 * The organizer's single surface in the duel room, on EVERY phase of it.
 *
 * The overrides used to live inside the pick-ban board, which meant they were
 * only reachable while that board was the screen: a hero session could not be
 * reset once the room had moved on to the map report, and the closing screen
 * offered nothing at all — yet those are exactly the moments an organizer is
 * called in. So the panel is hoisted to the room and rendered beside whatever
 * phase is up, with a tab per kind that HAS a session, and the readiness
 * override for the one phase that has neither.
 *
 * The grid's selection only belongs to the board on screen, so it is handed in
 * (`grid`) and only used while its own kind is the selected tab — an organizer
 * looking at the hero tab must not "perform action" with a map tile.
 */
export function PregameAdminPanel({
  encounterId,
  statesByKind,
  activeKind,
  sideNameOf,
  itemsByKind,
  bestOf,
  seriesWins,
  onMutated,
  grid = null
}: Readonly<{
  encounterId: number;
  statesByKind: Record<PickBanKind, PickBanState>;
  /** The kind the room itself is on, i.e. the tab to open by default. */
  activeKind: PickBanKind;
  sideNameOf: (side: PickBanSide) => string;
  /** Map and hero catalogs, so the history can name what was banned. */
  itemsByKind: Record<PickBanKind, Record<number, PickBanItemLike | undefined>>;
  /** Series length and the wins already confirmed — the technical loss's
   * default score is read off them, and neither is in a pick-ban state. */
  bestOf: number;
  seriesWins: { home: number; away: number } | null;
  onMutated: () => void;
  /** The board on screen, when one is: its selection and its own reset. */
  grid?: PickBanAdminSlot | null;
}>) {
  const t = useTranslations("pickBan.room");
  const withSession = KINDS.filter((kind) => statesByKind[kind].session != null);
  const [picked, setPicked] = useState<PickBanKind | null>(null);
  const kind =
    picked != null && withSession.includes(picked)
      ? picked
      : withSession.includes(activeKind)
        ? activeKind
        : (withSession[0] ?? null);

  // Readiness gates session creation, so it is only an override while nothing
  // has been created yet; afterwards the backend refuses to clear it (409) and
  // the honest undo is a reset, which the tabs below already offer.
  const readiness = statesByKind.map.readiness;
  const readinessMutation = useMutation({
    mutationFn: (input: { side: PickBanSide; ready: boolean }) =>
      adminService.setEncounterReadiness(encounterId, input),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.readinessFailed") })
  });

  const history = (
    <PregameRoomHistory
      encounterId={encounterId}
      sideNameOf={sideNameOf}
      itemsByKind={itemsByKind}
    />
  );

  if (kind == null) {
    // Only `not_ready` is a gate an organizer can lift from here: unknown
    // teams, an unpublished stage or a broken slot config would open no
    // session however ready both sides were, so offering the toggle there
    // would be a button that changes nothing.
    // The journal stays on screen even with nothing to override: "why is this
    // room not open yet" is one of the questions it answers.
    if (!KINDS.some((value) => statesByKind[value].reason === "not_ready")) return history;
    return (
      <div className="flex flex-col gap-3">
        <section className="rounded-xl border border-dashed border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-4">
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-[color:var(--aqt-amber)]" aria-hidden />
            <h2 className="text-sm font-semibold">{t("admin.readinessTitle")}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            {(["home", "away"] as const).map((side) => (
              <div key={side} className="flex items-center gap-2">
                <span className="text-sm font-medium">{sideNameOf(side)}</span>
                <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                  {t(readiness[side] ? "ready.stateReady" : "ready.statePending")}
                </span>
                <Button
                  size="sm"
                  variant={readiness[side] ? "outline" : "default"}
                  disabled={readinessMutation.isPending}
                  onClick={() => readinessMutation.mutate({ side, ready: !readiness[side] })}
                >
                  {readinessMutation.isPending && readinessMutation.variables?.side === side ? (
                    <Spinner className="mr-2" />
                  ) : null}
                  {t(readiness[side] ? "admin.readinessClear" : "admin.readinessSet")}
                </Button>
              </div>
            ))}
          </div>
        </section>
        {history}
      </div>
    );
  }

  const onThisKind = grid != null && grid.kind === kind;
  return (
    <div className="flex flex-col gap-3">
      <PregameAdminControls
        kind={kind}
        encounterId={encounterId}
        state={statesByKind[kind]}
        selectedItemId={onThisKind ? grid.selectedItemId : null}
        selectedItemName={onThisKind ? grid.selectedItemName : null}
        itemsById={itemsByKind[kind]}
        blind={onThisKind ? grid.blind : null}
        sideNameOf={sideNameOf}
        bestOf={bestOf}
        seriesWins={seriesWins}
        onMutated={() => {
          // The board's own reset also drops its selection and local draft; when
          // the organizer acted on the OTHER kind that board is untouched, so a
          // plain room refetch is the whole job.
          if (onThisKind) grid.onMutated();
          else onMutated();
        }}
        kindSwitch={
          withSession.length > 1 ? (
            <div role="tablist" aria-label={t("admin.kindSwitch")} className="flex gap-1">
              {withSession.map((value) => (
                <Button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={value === kind}
                  size="sm"
                  variant={value === kind ? "secondary" : "ghost"}
                  onClick={() => setPicked(value)}
                >
                  {t(`phase.${value}`)}
                </Button>
              ))}
            </div>
          ) : null
        }
      />
      {history}
    </div>
  );
}
