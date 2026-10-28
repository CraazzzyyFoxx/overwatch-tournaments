"use client";

import type { ReactNode } from "react";

import { useTranslations } from "next-intl";
import { useDraggable } from "@dnd-kit/core";
import { Armchair, GripVertical, RotateCw, X } from "lucide-react";

import { AWAY_CHIP_CLASS, lobbyLetter, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { HandleLabel } from "@/components/HandleLabel";
import { RankCrest } from "@/components/RankCrest";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  RotationRecommendation
} from "@/services/custom-game.service";

import { averageRank, getLineupIssue, playerLabel, type MixOwner } from "../pickup-lineup";
import { RolePriorityRail } from "./RolePriorityRail";

/**
 * Marks a subtree as owning its own clicks, so the clickable row skips it.
 *
 * A plain wrapper with no handler: putting `onClick` on a `<span>` to swallow
 * the bubble made the row's own logic depend on a non-interactive element
 * having a listener, which the design gate rightly rejects. The row filters by
 * this attribute instead — the same `data-card-action` convention the
 * tournament pool row uses.
 */
function RowAction({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span data-card-action className="flex shrink-0 items-center">
      {children}
    </span>
  );
}

/**
 * The rotation-fairness verdict for one row, as a single 18px icon -- a
 * `neutral` verdict (or none loaded yet) renders nothing, so a mix with no
 * map history yet looks exactly like it did before this existed. `must_play`
 * (owed a seat the longest) and `should_rest` (played the most in a row) are
 * the only two a host acts on, so they are the only two with an icon; the
 * reason code, worded with the streak it names, goes into the tooltip instead
 * of a wider label competing with the role rail for room. A row the host already
 * pinned (the `must_play` column) never renders one either -- the backend always
 * verdicts a pin `must_play` too (see `mix_rotation.recommend_rotation`), and
 * repeating "owed a seat" next to a seat already guaranteed by the Pin icon
 * is the same fact said twice.
 */
function RotationHintBadge({
  hint,
  pinned
}: Readonly<{ hint: RotationRecommendation | undefined; pinned: boolean }>) {
  const t = useTranslations("mixes.rotation");
  if (!hint || hint.status === "neutral" || pinned) {
    return null;
  }
  const isOwed = hint.status === "must_play";
  const Icon = isOwed ? RotateCw : Armchair;
  let label: string;
  switch (hint.reason) {
    case "owed_seat":
      label = t("owed_seat", { count: hint.consecutive_sat });
      break;
    case "played_streak":
      label = t("played_streak", { count: hint.consecutive_played });
      break;
    case "played_most":
      label = t("played_most", { count: hint.games_played });
      break;
    default:
      label = t(hint.reason);
  }
  return (
    <IconTooltip
      label={label}
      className={cn(
        "size-[18px] shrink-0 items-center justify-center",
        isOwed ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-faint)]"
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
    </IconTooltip>
  );
}

type LineupRowProps = {
  row: CustomGamePlayer;
  /** This member's rotation-fairness verdict, if the fetch has one. */
  rotationHint: RotationRecommendation | undefined;
  /** The mix owner's game: its roles, tints and the grid the row's ranks are on. */
  owner: MixOwner;
  canWrite: boolean;
  /** More than one lobby: the row says which one seated this player, or that nobody did. */
  lobbyCount: number;
  saving: boolean;
  /** Benched rows read de-emphasised and freeze their role rail. */
  dimmed: boolean;
  onPatch: (patch: CustomGamePlayerPatch) => void;
  onOpen: () => void;
  onRemove: () => void;
};

/**
 * Which lobby seated this player, derived server-side from each lobby's
 * selected variant (`current_lobby`). `null` is "waiting" -- in the pool, in
 * nobody's teams this round -- which is exactly the state a host scans for
 * before rebalancing a lobby, so it is spelled out rather than left blank.
 */
function LineupLobbyBadge({ currentLobby }: Readonly<{ currentLobby: number | null | undefined }>) {
  const t = useTranslations("mixes.lobbies");
  const seated = currentLobby != null;
  return (
    <IconTooltip
      label={seated ? t("seatedIn", { letter: lobbyLetter(currentLobby) }) : t("waitingTitle")}
      className="shrink-0"
    >
      <span
        data-testid="lineup-lobby"
        aria-hidden="true"
        className={cn(
          "flex items-center justify-center rounded px-1 text-label font-bold uppercase tracking-label",
          seated
            ? cn(teamAccent(currentLobby).bar, "text-[color:var(--aqt-bg)]")
            : "text-[color:var(--aqt-fg-faint)]"
        )}
      >
        {seated ? lobbyLetter(currentLobby) : t("waiting")}
      </span>
    </IconTooltip>
  );
}

/**
 * One lineup row, draggable between the three `LineupColumn`s.
 *
 * The whole row is both the click target that opens the drawer and the drag
 * source that moves it between columns — a `PointerSensor` activation
 * distance (see `useDragSensors`) tells the two apart, the same pattern the
 * matchup board's seat rows already use. For a writer the name is also a real
 * button onto the same drawer, the keyboard's way in. A click that started
 * inside a `data-card-action` control still belongs to that control, never the
 * row's own onOpen.
 */
export function LineupRow({
  row,
  rotationHint,
  owner,
  canWrite,
  lobbyCount,
  saving,
  dimmed,
  onPatch,
  onOpen,
  onRemove
}: Readonly<LineupRowProps>) {
  const t = useTranslations("mixes.lineup");
  const tRoom = useTranslations("mixes.room");
  const { grid } = owner;
  const label = playerLabel(row);
  const issue = getLineupIssue(row, owner.roles);
  const rank = averageRank(row, owner.roles);
  const canDrag = canWrite && !saving;
  const draggable = useDraggable({
    id: String(row.workspace_member_id),
    data: { row },
    disabled: !canDrag
  });

  return (
    <li
      ref={(node) => draggable.setNodeRef(node)}
      {...draggable.listeners}
      {...draggable.attributes}
      title={canWrite ? t("rowTitle", { name: label }) : undefined}
      onClick={(event) => {
        // The sheet is a writer's tool: a read-only viewer opens nothing.
        if (!canWrite) return;
        // `event.target` on a click landing on the role/remove buttons' SVG
        // icon is an `SVGElement`, which is not an `HTMLElement` \u2014 checking
        // the narrower type let those clicks fall through to `onOpen()`.
        if (event.target instanceof Element && event.target.closest("[data-card-action]")) {
          return;
        }
        onOpen();
      }}
      className={cn(
        "flex items-center gap-2 rounded-lg border border-transparent px-2 py-2 transition-colors",
        "hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-2)]",
        canDrag && "touch-none active:cursor-grabbing",
        issue && "border-[color:color-mix(in_srgb,var(--aqt-amber)_35%,transparent)]",
        draggable.isDragging ? "opacity-30" : dimmed && "opacity-60"
      )}
    >
      <GripVertical
        className={cn(
          "size-3.5 shrink-0",
          canDrag ? "text-[color:var(--aqt-fg-faint)]" : "text-transparent"
        )}
        aria-hidden="true"
      />

      {canWrite ? (
        <Button
          type="button"
          variant="link"
          size="inline"
          data-card-action
          aria-label={t("advancedFor", { name: label })}
          onClick={onOpen}
          className="mr-auto min-w-0 justify-start"
        >
          <HandleLabel
            handle={label}
            className="text-caption font-semibold text-[color:var(--aqt-fg)]"
            tagClassName="text-label"
          />
        </Button>
      ) : (
        <HandleLabel
          handle={label}
          className="flex-1 text-caption font-semibold text-[color:var(--aqt-fg)]"
          tagClassName="text-label"
        />
      )}

      {row.away ? <span className={AWAY_CHIP_CLASS}>{tRoom("away")}</span> : null}
      {lobbyCount > 1 ? <LineupLobbyBadge currentLobby={row.current_lobby} /> : null}
      <RotationHintBadge hint={rotationHint} pinned={row.participation === "must_play"} />

      {owner.showsRoles ? (
        <RowAction>
          <RolePriorityRail
            row={row}
            owner={owner}
            label={label}
            canWrite={canWrite && !dimmed}
            saving={saving}
            onPatch={onPatch}
          />
        </RowAction>
      ) : null}

      <div className="flex w-[92px] shrink-0 items-center justify-end gap-1.5">
        <RankCrest rank={rank} grid={grid} />
        {/* One number, one meaning: the mean of the effective ranks the balancer
            will use. The `*` that used to mark a per-mix pin is gone with the pin
            itself — which layer each role resolved from is named in the sheet. */}
        <span
          title={t("meanRank")}
          className="text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]"
        >
          {rank ?? "\u2014"}
        </span>
      </div>

      {canWrite ? (
        <RowAction>
          <IconTooltip control label={t("remove")}>
            <Button type="button" variant="ghost-destructive" size="icon-sm" onClick={onRemove} className="shrink-0">
              <X aria-hidden="true" />
              <span className="sr-only">{t("removeNamed", { name: label })}</span>
            </Button>
          </IconTooltip>
        </RowAction>
      ) : null}
    </li>
  );
}

/** The dragged row's own card, detached from its column, following the pointer. */
export function LineupDragPreview({ row, owner }: Readonly<{ row: CustomGamePlayer; owner: MixOwner }>) {
  const label = playerLabel(row);
  const rank = averageRank(row, owner.roles);

  return (
    <Card
      className="flex cursor-grabbing items-center gap-2 rounded-lg border-[color:var(--aqt-teal)] px-2.5 py-2"
    >
      <GripVertical
        className="size-3.5 shrink-0 text-[color:var(--aqt-fg-faint)]"
        aria-hidden="true"
      />
      <HandleLabel
        handle={label}
        className="flex-1 text-caption font-semibold text-[color:var(--aqt-fg)]"
        tagClassName="text-label"
      />
      <span className="shrink-0 text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]">
        {rank ?? "\u2014"}
      </span>
    </Card>
  );
}
