"use client";

import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/card";
import {
  Table,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import type {
  BalancerRosterKey,
  InternalBalancePayload,
} from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { BalanceTeamHeader } from "./BalanceTeamHeader";
import { DroppableRoleSection } from "./BalanceEditorPlayerRows";
import { isRoleDropAllowed, type BalanceActiveDrag } from "./balance-editor-helpers";
import type { RemoteDrag } from "./useBalancerDragGhosts";

type BalanceEditorTeamCardProps = {
  team: InternalBalancePayload["teams"][number];
  teamIndex: number;
  /** Roster buckets to draw, in order — the ones the tournament's shape fields. */
  bucketKeys: BalancerRosterKey[];
  divisionGrid: DivisionGrid;
  /** The tournament owner's role dictionary: names the buckets and glyphs the rows. `null` while it loads. */
  ontology: RoleOntology | null;
  selectedPlayerId?: number | null;
  collapsed: boolean;
  activeDrag?: BalanceActiveDrag | null;
  /** Other users' in-progress drags currently targeting this team. */
  remoteDrags?: RemoteDrag[];
  resolveActorName?: (userId: number) => string;
  onSelectPlayer?: (playerId: number | null) => void;
  onToggleTeam?: (teamId: number) => void;
};

export function BalanceEditorTeamCard({
  team,
  teamIndex,
  bucketKeys,
  divisionGrid,
  ontology,
  selectedPlayerId,
  activeDrag = null,
  remoteDrags = [],
  resolveActorName,
  onSelectPlayer,
}: Readonly<BalanceEditorTeamCardProps>) {
  const t = useTranslations("balancerTool.editor");
  const slotLabel = useSlotLabel(ontology);

  return (
    <Card className="overflow-hidden">
      <BalanceTeamHeader team={team} teamIndex={teamIndex} />
      {remoteDrags.length > 0 ? (
        <div className="flex flex-col gap-1 border-b border-cyan-300/15 bg-cyan-500/5 px-4 py-2">
          {remoteDrags.map((drag) => (
            <div
              key={drag.userId}
              className="flex items-center gap-1.5 text-xs text-cyan-100/80"
            >
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/70" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-300" />
              </span>
              <span className="font-medium text-cyan-50/90">
                {resolveActorName?.(drag.userId) ?? t("remoteDrag.unknownUser", { id: drag.userId })}
              </span>
              <span className="text-cyan-100/55">{t("remoteDrag.moving")}</span>
              <span className="truncate font-medium text-cyan-50/90" title={drag.playerName}>
                {drag.playerName || t("remoteDrag.player")}
              </span>
              {drag.overRoleKey ? (
                <span className="text-cyan-100/55">&rarr; {slotLabel(drag.overRoleKey)}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <Table wrapperClassName="overflow-x-auto overflow-y-visible" className="min-w-90">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 w-13 px-4">{t("columns.role")}</TableHead>
            <TableHead className="h-8 min-w-45 px-0">{t("columns.player")}</TableHead>
            <TableHead className="h-8 w-18 px-2 text-center">{t("columns.rank")}</TableHead>
            <TableHead className="h-8 w-22 px-3 text-center">{t("columns.prefs")}</TableHead>
          </TableRow>
        </TableHeader>
        {bucketKeys.map((roleKey) => (
          <DroppableRoleSection
            key={`${team.id}-${roleKey}`}
            teamIndex={teamIndex}
            containerId={`${teamIndex}:${roleKey}`}
            roleKey={roleKey}
            players={team.roster[roleKey]}
            divisionGrid={divisionGrid}
            ontology={ontology}
            selectedPlayerId={selectedPlayerId}
            dropDisabled={activeDrag != null && !isRoleDropAllowed(activeDrag, roleKey)}
            onSelectPlayer={onSelectPlayer}
          />
        ))}
      </Table>
    </Card>
  );
}
