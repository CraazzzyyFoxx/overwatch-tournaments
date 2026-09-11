"use client";

import { useState } from "react";
import { Settings2 } from "lucide-react";

import {
  DEFAULT_COMFORT_TILT,
  DEFAULT_ROLE_WEIGHT,
  MAX_ROLE_WEIGHT,
  SLOT_LABELS,
  mixConfigPatch,
  roleWeightsOf,
  tiltOf,
  withRoleWeight
} from "@/app/balancer/mix/mix-balancer-config";

import { Button } from "@/components/ui/button";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { RosterShapeEditor } from "@/components/roster-shape/RosterShapeEditor";
import { payloadTotalError } from "@/components/roster-shape/roster-shape-editor.model";
import { orderSlotCodes, type RosterSlotMap } from "@/lib/roster-shape";
import { Slider } from "@/components/ui/slider";
import type { CustomGame, MixBalancerConfig } from "@/services/custom-game.service";

/** What `onSave` writes: the four independent config knobs this dialog owns. */
export type PickupMixConfigInput = {
  roleMask: RosterSlotMap | null;
  /** The rank-adjustment-per-win, or `null` to disable it. */
  pointsPerWin: number | null;
  /**
   * This mix's channel override, or `null` to follow the workspace channel.
   * `undefined` when the viewer may not set one -- nothing to write.
   */
  discordChannelId: string | null | undefined;
  /**
   * The whole overrides blob to store, already merged onto what the mix had:
   * `set_balancer_config` replaces rather than patches.
   */
  balancerConfig: MixBalancerConfig | null;
};

interface PickupMixConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  game: CustomGame | null | undefined;
  /** The workspace whose Discord server the channel list comes from. */
  workspaceId: number;
  /** Host + not-terminal, same gate every other mix write uses. */
  canWrite: boolean;
  /**
   * Workspace admin. The channel a mix shouts into is the workspace's Discord,
   * so an ordinary host reads it and posts to it but cannot repoint it --
   * `custom.set_discord_channel` 403s them (see `_require_workspace_admin`).
   */
  canSetChannel: boolean;
  saving: boolean;
  onSave: (input: PickupMixConfigInput) => void;
}

/**
 * Per-mix settings: team composition -- the tournament settings tab's
 * roster-shape editor, wired to `CustomGame.settings.role_mask` instead of
 * `Tournament.roster_slots_json`. A mix has no tournament level of its own:
 * "inherit" here means the workspace default one level up, exactly what
 * `CustomGameService.roster_shape` resolves against. The rank-adjustment-
 * per-win: recording a win/loss then bumps the host's own rank book by this
 * many points, letting a night of mixes self-correct without the host
 * retyping ranks between games. And the Discord channel the matchup is posted
 * to, so a lobby reads the teams where it already talks.
 */
export function PickupMixConfigDialog({
  open,
  onOpenChange,
  game,
  workspaceId,
  canWrite,
  canSetChannel,
  saving,
  onSave
}: Readonly<PickupMixConfigDialogProps>) {
  const [pending, setPending] = useState<RosterSlotMap | null>(game?.settings.role_mask ?? null);
  const [pendingPoints, setPendingPoints] = useState<number | null>(
    game?.settings.points_per_win ?? null,
  );
  // The picker speaks in strings and has no null: "" is its no-channel value.
  const [pendingChannel, setPendingChannel] = useState(game?.settings.discord_channel_id ?? "");
  const [pendingTilt, setPendingTilt] = useState(() => tiltOf(game?.settings.balancer_config));
  const [pendingWeights, setPendingWeights] = useState(() => roleWeightsOf(game?.settings.balancer_config));
  const [wasOpen, setWasOpen] = useState(open);

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setPending(game?.settings.role_mask ?? null);
      setPendingPoints(game?.settings.points_per_win ?? null);
      setPendingChannel(game?.settings.discord_channel_id ?? "");
      setPendingTilt(tiltOf(game?.settings.balancer_config));
      setPendingWeights(roleWeightsOf(game?.settings.balancer_config));
    }
  }

  const error = payloadTotalError(pending);
  const channelEditable = canWrite && canSetChannel;
  const workspaceChannel = game?.settings.workspace_discord_channel_id ?? null;
  // Weightable lines follow the shape being edited, not the stored one, so
  // adding a flex slot above puts its weight row on screen straight away.
  const weightableCodes = orderSlotCodes(pending ?? game?.roster_shape?.slots ?? {});

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Mix settings
          </DialogTitle>
          <DialogDescription>
            Team composition and how recording a result affects the roster&apos;s ranks.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Team composition</Label>
          <RosterShapeEditor
            entity="mix"
            value={pending}
            effective={game?.roster_shape ?? null}
            disabled={!canWrite}
            onChange={setPending}
          />
        </div>

        <div className="space-y-3 border-t border-[color:var(--aqt-border)] pt-4">
          <div className="space-y-1.5">
            <Label asChild>
              <span>
                Balancing
                <span className="ml-1.5 text-xs text-muted-foreground">
                  (rank balance vs role comfort)
                </span>
              </span>
            </Label>
            <Slider
              aria-label="Rank balance versus role comfort"
              min={0}
              max={100}
              step={5}
              disabled={!canWrite}
              value={[Math.round(pendingTilt * 100)]}
              onValueChange={([next]) => setPendingTilt((next ?? 50) / 100)}
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Even ranks</span>
              <span className="tabular-nums">
                {pendingTilt === DEFAULT_COMFORT_TILT ? "Balanced" : `${Math.round(pendingTilt * 100)}% comfort`}
              </span>
              <span>Preferred roles</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Pulled left, the engine only cares how evenly the two teams&apos; ranks split. Pulled
              right, it will accept a wider rank gap to seat more players on the role they asked
              for. The middle is its own default weighting.
            </p>
          </div>

          {weightableCodes.length > 0 ? (
            <div className="space-y-1.5">
              <Label>
                Line importance
                <span className="ml-1.5 text-xs text-muted-foreground">(1 = normal)</span>
              </Label>
              <div className="flex flex-wrap gap-2">
                {weightableCodes.map((code) => (
                  <div key={code} className="flex items-center gap-2">
                    <Label htmlFor={`mix-role-weight-${code}`} className="text-xs text-muted-foreground">
                      {SLOT_LABELS[code]}
                    </Label>
                    <NumberInput
                      id={`mix-role-weight-${code}`}
                      min={0}
                      max={MAX_ROLE_WEIGHT}
                      disabled={!canWrite}
                      placeholder="1"
                      value={pendingWeights[code] ?? DEFAULT_ROLE_WEIGHT}
                      onValueChange={(next) =>
                        setPendingWeights((current) => withRoleWeight(current, code, next))
                      }
                      className="h-8 w-16 bg-background/50 px-2 text-center tabular-nums"
                    />
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                How hard the engine works to match that line across the two teams. Raise Tank and a
                tank mismatch costs more than a support one.
              </p>
            </div>
          ) : null}
        </div>

        <div className="space-y-1.5 border-t border-[color:var(--aqt-border)] pt-4">
          <Label htmlFor="points-per-win">
            Points per win
            <span className="ml-1.5 text-xs text-muted-foreground">
              (rank points, empty = off)
            </span>
          </Label>
          <NumberInput
            id="points-per-win"
            integer
            min={0}
            max={1000}
            disabled={!canWrite}
            placeholder="e.g. 25"
            value={pendingPoints}
            onValueChange={setPendingPoints}
          />
          <p className="text-xs text-muted-foreground">
            Recording who won then bumps every winning player&apos;s rank by this many points, and every
            losing player&apos;s down by the same, in the host&apos;s own book.
          </p>
        </div>

        <div className="space-y-1.5 border-t border-[color:var(--aqt-border)] pt-4">
          <Label>
            Discord channel
            <span className="ml-1.5 text-xs text-muted-foreground">
              (where Post to Discord sends the matchup)
            </span>
          </Label>
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <DiscordChannelSelect
                workspaceId={workspaceId}
                value={pendingChannel}
                onChange={setPendingChannel}
                disabled={!channelEditable}
                ariaLabel="Discord channel"
                placeholder={workspaceChannel ? "Workspace channel" : "No channel"}
              />
            </div>
            {channelEditable && pendingChannel !== "" ? (
              <Button variant="ghost" size="sm" onClick={() => setPendingChannel("")}>
                Clear
              </Button>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">
            {canSetChannel
              ? "Empty posts to the workspace channel; picking one here overrides it for this mix only. The bot must be in this workspace's Discord server and allowed to post in the channel."
              : "Set by workspace admins. This mix posts to the workspace channel unless an admin points it somewhere else."}
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!canWrite || saving || error !== null}
            onClick={() =>
              onSave({
                roleMask: pending,
                pointsPerWin: pendingPoints,
                // Nothing to write for a non-admin: the field was read-only,
                // and sending the unchanged value would 403 the whole save.
                discordChannelId: channelEditable
                  ? pendingChannel === ""
                    ? null
                    : pendingChannel
                  : undefined,
                balancerConfig: mixConfigPatch(
                  game?.settings.balancer_config,
                  pendingTilt,
                  pendingWeights,
                ),
              })
            }
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
