"use client";

import { CheckCircle2, History, Plus, Save } from "lucide-react";
import { SortableRows } from "@/components/kit/SortableRows";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { cn } from "@/lib/utils";
import type {
  AdminRegistration,
  BalancerPlayerRecord,
  BalancerPlayerUpdateInput,
  BalancerRoleCode
} from "@/types/balancer-admin.types";
import { getRegistrationBattleTags } from "@/components/balancer/balancer-page-helpers";
import { BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import RankHistory from "@/components/RankHistory";
import { Spinner } from "@/components/ui/spinner";

import { PlayerEditHistoryPanel } from "./PlayerEditHistoryPanel";
import { SortableRoleEntry } from "./PlayerEditRoleRow";
import { ROLE_OPTIONS, isComputedReady } from "./playerEditSheet.model";
import { usePlayerEditForm } from "./usePlayerEditForm";

type PlayerEditModalProps = {
  player: BalancerPlayerRecord;
  registration?: AdminRegistration | null;
  statusOptions?: {
    registration: {
      system: Array<{ value: string; name: string }>;
      custom: Array<{ value: string; name: string }>;
    };
    balancer: {
      system: Array<{ value: string; name: string }>;
      custom: Array<{ value: string; name: string }>;
    };
  };
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (playerId: number, payload: BalancerPlayerUpdateInput) => void;
  onRemove?: (playerId: number) => void;
  saving?: boolean;
  rankHistory?: Partial<Record<BalancerRoleCode, number>> | null;
};

export function PlayerEditModal({
  player,
  registration = null,
  statusOptions,
  open,
  onOpenChange,
  onSave,
  onRemove,
  saving = false,
  rankHistory = null
}: Readonly<PlayerEditModalProps>) {
  const form = usePlayerEditForm({ player, registration, rankHistory, open, onSave });
  const { roleEntries, history } = form;

  const battleTags = getRegistrationBattleTags(registration, player.battle_tag);
  const primaryBattleTag = battleTags[0] ?? player.battle_tag;
  const smurfTags = battleTags.slice(1);
  const computedReady = isComputedReady(roleEntries);
  const hasOverride = roleEntries.some((entry) => entry.rank_source === "registration");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col overflow-hidden border-border bg-popover/95 p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/50 backdrop-blur-xl sm:max-w-[640px] [&>button:last-child]:right-4 [&>button:last-child]:top-4 [&>button:last-child]:z-20 [&>button:last-child]:flex [&>button:last-child]:h-8 [&>button:last-child]:w-8 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>button:last-child]:rounded-lg [&>button:last-child]:border [&>button:last-child]:border-[color:var(--aqt-border-2)] [&>button:last-child]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:p-0 [&>button:last-child]:text-[color:var(--aqt-fg-muted)] [&>button:last-child]:backdrop-blur-sm [&>button:last-child]:hover:bg-[color:var(--aqt-overlay-3)] [&>button:last-child]:hover:text-[color:var(--aqt-fg)] [&>button:last-child]:data-[state=open]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:data-[state=open]:text-[color:var(--aqt-fg-muted)]"
      >
        <SheetHeader
          className={cn(
            "shrink-0 border-b border-[color:var(--aqt-border)] px-4 pb-2.5 pt-3 sm:px-5 sm:pb-3 sm:pt-3.5",
            onRemove ? "pr-20 sm:pr-24" : "pr-14 sm:pr-16"
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle className="text-base font-semibold tracking-tight text-[color:var(--aqt-fg)]">
              {primaryBattleTag}
            </SheetTitle>
            <BattleTagCopyButton battleTag={primaryBattleTag} className="h-6 w-6" />
            {form.isFlex ? (
              <Badge className="h-5 border-emerald-400/25 bg-emerald-400/10 px-2 text-label text-emerald-200 hover:bg-emerald-400/10">
                Flex
              </Badge>
            ) : null}
          </div>
          <SmurfTagStrip smurfTags={smurfTags} className="mt-1.5" />
          <SheetDescription className="text-xs text-[color:var(--aqt-fg-dim)]">
            Roles, ratings, and balancer participation.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
          <div className="grid gap-2.5 lg:grid-cols-2">
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-[color:var(--aqt-fg)]">Balancer status</span>
                {registration ? (
                  <StatusMetaBadge meta={registration.balancer_status_meta} className="h-5 text-label" />
                ) : (
                  <Badge
                    className={cn(
                      "h-5 px-2 text-label",
                      computedReady
                        ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                        : "border-orange-400/25 bg-orange-400/10 text-orange-200"
                    )}
                  >
                    {computedReady ? "Ready" : "Incomplete"}
                  </Badge>
                )}
              </div>
            </div>
            <div
              className={cn(
                "rounded-lg border px-3 py-2",
                form.isFlex
                  ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                  : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="is-flex" className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]">
                  Flex player
                </Label>
                <Switch
                  id="is-flex"
                  checked={form.isFlex}
                  onCheckedChange={form.setIsFlex}
                  aria-label="Flex player"
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Roles</Label>
              <div className="flex flex-nowrap items-center gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                  onClick={form.addRole}
                  disabled={roleEntries.length >= ROLE_OPTIONS.length}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  Add role
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                  onClick={() => void history.load()}
                  disabled={history.loading}
                >
                  {history.loading ? (
                    <Spinner className="mr-1 size-3" />
                  ) : (
                    <History className="mr-1 h-3 w-3" />
                  )}
                  Load from history
                </Button>
              </div>
            </div>

            {history.requested ? (
              <PlayerEditHistoryPanel
                history={history}
                roleEntries={roleEntries}
                getDivisionName={form.getHistoryDivisionName}
                getOriginalDivisionName={form.getOriginalDivisionName}
              />
            ) : null}

            <div className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <Label htmlFor="pin-tournament" className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]">
                Only this tournament
              </Label>
              <div className="flex items-center gap-2">
                {hasOverride ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)]"
                    disabled={saving}
                    onClick={form.handleClearPin}
                  >
                    Use workspace rank
                  </Button>
                ) : null}
                <Switch
                  id="pin-tournament"
                  checked={form.pinToTournament}
                  onCheckedChange={form.setPinToTournament}
                  aria-label="Only this tournament"
                />
              </div>
            </div>

            <SortableRows
              items={roleEntries}
              getId={(entry, index) => `${entry.role}-${index}`}
              onReorder={form.reorderRoles}
              className="space-y-2"
            >
              {(entry, index) => (
                <SortableRoleEntry
                  key={`${entry.role}-${index}`}
                  id={`${entry.role}-${index}`}
                  entry={entry}
                  index={index}
                  resolveDivision={form.resolveDivision}
                  getDivisionName={form.getDivisionName}
                  onUpdate={form.updateEntry}
                  onRemove={form.removeEntry}
                  subtypeOptions={form.subtypeOptions}
                />
              )}
            </SortableRows>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Live rank (OverFast)</Label>
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
              {player.user_id != null ? (
                <RankHistory userId={player.user_id} />
              ) : (
                <RankHistory battleTag={primaryBattleTag} />
              )}
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Admin notes</Label>
            <Textarea
              value={form.notes}
              onChange={(event) => form.setNotes(event.target.value)}
              className="min-h-14 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-1.5 text-xs text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-faint)]"
              placeholder="Notes about availability, role comfort, or balancing caveats."
            />
          </div>
          {registration && statusOptions ? (
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Registration status</Label>
                <Select value={form.registrationStatus} onValueChange={form.setRegistrationStatus}>
                  <SelectTrigger className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-xs text-[color:var(--aqt-fg)]">
                    <SelectValue placeholder="Select registration status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.registration.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · System
                      </SelectItem>
                    ))}
                    {statusOptions.registration.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · Custom
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Balancer status</Label>
                <Select
                  value={form.registrationBalancerStatus}
                  onValueChange={form.setRegistrationBalancerStatus}
                >
                  <SelectTrigger className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-xs text-[color:var(--aqt-fg)]">
                    <SelectValue placeholder="Select balancer status" />
                  </SelectTrigger>
                  <SelectContent>
                    {form.registrationBalancerStatus === "ready" ||
                    form.registrationBalancerStatus === "incomplete" ? (
                      <SelectItem value={form.registrationBalancerStatus} disabled>
                        {form.registrationBalancerStatus === "ready" ? "Ready" : "Incomplete"} · Computed
                      </SelectItem>
                    ) : null}
                    {statusOptions.balancer.system
                      .filter((option) => option.value !== "ready" && option.value !== "incomplete")
                      .map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.name} · System
                        </SelectItem>
                      ))}
                    {statusOptions.balancer.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · Custom
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-label text-[color:var(--aqt-fg-dim)]">
                    Ready/Incomplete are computed from role ranks. Pick Excluded to pull this player from the pool.
                  </p>
                  {form.registrationBalancerStatus !== "ready" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-6 shrink-0 gap-1 whitespace-nowrap border-emerald-500/30 bg-emerald-500/10 px-2 text-label text-emerald-200 hover:bg-emerald-500/20 hover:text-emerald-100"
                      disabled={saving}
                      onClick={form.handleMoveToReady}
                      title="Saves your pending edits, then recomputes this player's balancer status from their current role ranks"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Move to ready
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <SheetFooter className="shrink-0 border-t border-[color:var(--aqt-border)] px-4 py-2.5 sm:justify-between sm:space-x-0 sm:px-5">
          <div className="text-label text-[color:var(--aqt-fg-dim)]">
            Manual edits always win until you explicitly load and apply new history values.
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-3 text-xs text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={form.handleSave}
              disabled={saving}
              className="h-8 bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90"
            >
              <Save className="mr-1 h-3.5 w-3.5" />
              Save
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
