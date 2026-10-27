"use client";

import { CheckCircle2, History, Plus, Save } from "lucide-react";
import { useTranslations } from "next-intl";
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
import { TONE_TINT } from "@/components/ui/tone";
import { cn } from "@/lib/utils";
import type {
  AdminRegistration,
  BalancerPlayerRecord,
  BalancerPlayerUpdateInput
} from "@/types/balancer-admin.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { showsRoles } from "@/lib/roster/ontology";
import { AdditionalHandleStrip, HandleCopyButton } from "./HandleCopyControls";
import RankHistory from "@/components/RankHistory";
import { Spinner } from "@/components/ui/spinner";

import { PlayerEditHistoryPanel } from "./PlayerEditHistoryPanel";
import { SortableRoleEntry } from "./PlayerEditRoleRow";
import { isComputedReady } from "./playerEditSheet.model";
import { usePlayerEditForm } from "./usePlayerEditForm";

type PlayerEditModalProps = {
  player: BalancerPlayerRecord;
  registration?: AdminRegistration | null;
  discipline: string | undefined;
  /** The owner game's metadata (role names, glyphs, tints, capabilities); `null` while it loads. */
  ontology?: DisciplineMetadata | null;
  divisionGridVersionId: number | null | undefined;
  divisionGridVersion?: DivisionGridVersion | null;
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
  saving?: boolean;
};

export function PlayerEditModal({
  player,
  registration = null,
  discipline,
  ontology = null,
  divisionGridVersionId,
  divisionGridVersion,
  statusOptions,
  open,
  onOpenChange,
  onSave,
  saving = false
}: Readonly<PlayerEditModalProps>) {
  const t = useTranslations("balancerTool.playerEdit.sheet");
  const tCommon = useTranslations("common");
  const form = usePlayerEditForm({
    player,
    registration,
    discipline,
    ontology,
    divisionGridVersionId,
    divisionGridVersion,
    open: open && discipline !== undefined,
    onSave
  });
  const { roleEntries, history } = form;

  const primaryHandle = player.identity;
  const computedReady = isComputedReady(roleEntries);
  const hasOverride = roleEntries.some((entry) => entry.rank_source === "registration");
  // Only a game that collects native ranks has a live rank to show or to suggest: no other game gets a placeholder.
  const nativeRankName = ontology?.discipline.capabilities.native_rank_collection
    ? ontology.discipline.name
    : null;
  // A game with one rated role edits its rank alone: no role list to order, no role to add, turn off or remove.
  const showsRoleList = showsRoles(ontology);

  return (
    <Sheet
      open={open && discipline !== undefined && form.divisionGrid.tiers.length > 0}
      onOpenChange={onOpenChange}
    >
      <SheetContent
        side="right"
        variant="panel"
        className="w-full sm:max-w-[640px]"
      >
        <SheetHeader variant="panel">
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle>
              {primaryHandle}
            </SheetTitle>
            <HandleCopyButton handle={primaryHandle} className="h-6 w-6" />
            {form.isFlex ? (
              <Badge hue="var(--aqt-flex)">
                {t("flex")}
              </Badge>
            ) : null}
          </div>
          <AdditionalHandleStrip additionalHandles={player.additional_handles} className="mt-1.5" />
          <SheetDescription>{t("description")}</SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
          <div className="grid gap-2.5 lg:grid-cols-2">
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium">
                  {t("balancerStatus")}
                </span>
                {registration ? (
                  <StatusMetaBadge
                    meta={registration.balancer_status_meta}
                    className="h-5"
                  />
                ) : (
                  <Badge size="sm" tone={computedReady ? "success" : "warning"} className="h-5">
                    {computedReady ? t("ready") : t("incomplete")}
                  </Badge>
                )}
              </div>
            </div>
            {/* A game without Full flex (`discipline.flex`) offers no switch for it. */}
            {ontology?.discipline.flex === false ? null : (
              <div
                className={cn(
                  "rounded-lg border px-3 py-2",
                  form.isFlex
                    ? cn(TONE_TINT, "[--tone-hue:var(--aqt-flex)]")
                    : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <Label
                    htmlFor="is-flex"
                    className="cursor-pointer"
                  >
                    {t("flexPlayer")}
                  </Label>
                  <Switch
                    id="is-flex"
                    checked={form.isFlex}
                    onCheckedChange={form.setIsFlex}
                    aria-label={t("flexPlayer")}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label>
                {showsRoleList ? t("roles") : t("rank")}
              </Label>
              <div className="flex flex-nowrap items-center gap-1.5">
                {showsRoleList ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                    onClick={form.addRole}
                    disabled={form.addableRole === null}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    {t("addRole")}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                  onClick={() => void history.load()}
                  disabled={history.loading}
                >
                  {history.loading ? (
                    <Spinner className="mr-1 size-3" />
                  ) : (
                    <History className="mr-1 h-3 w-3" />
                  )}
                  {t("loadFromHistory")}
                </Button>
              </div>
            </div>

            {history.requested ? (
              <PlayerEditHistoryPanel
                history={history}
                roleEntries={roleEntries}
                workspaceGrid={form.workspaceGrid}
                ontology={ontology}
                getDivisionName={form.getHistoryDivisionName}
                getOriginalDivisionName={form.getOriginalDivisionName}
              />
            ) : null}

            <div className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <Label
                htmlFor="pin-tournament"
                className="cursor-pointer"
              >
                {t("onlyThisTournament")}
              </Label>
              <div className="flex items-center gap-2">
                {hasOverride ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)]"
                    disabled={saving}
                    onClick={form.handleClearPin}
                  >
                    {t("useWorkspaceRank")}
                  </Button>
                ) : null}
                <Switch
                  id="pin-tournament"
                  checked={form.pinToTournament}
                  onCheckedChange={form.setPinToTournament}
                  aria-label={t("onlyThisTournament")}
                />
              </div>
            </div>

            <SortableRows
              items={roleEntries}
              getId={(entry, index) => `${entry.role}-${index}`}
              onReorder={form.reorderRoles}
              className="space-y-2"
            >
              {(entry, index) =>
                // A one-role game shows its sole role's rank alone; any other stored entry is kept, not shown.
                form.soleRole === null || entry.role === form.soleRole ? (
                  <SortableRoleEntry
                    key={`${entry.role}-${index}`}
                    id={`${entry.role}-${index}`}
                    entry={entry}
                    index={index}
                    grid={form.divisionGrid}
                    resolveDivision={form.resolveDivision}
                    getDivisionName={form.getDivisionName}
                    onUpdate={form.updateEntry}
                    onRemove={form.removeEntry}
                    subtypeOptions={form.subtypeOptions}
                    ontology={ontology}
                    nativeRankName={nativeRankName}
                    showsRole={showsRoleList}
                  />
                ) : null
              }
            </SortableRows>
          </div>

          {nativeRankName !== null ? (
            <div className="space-y-2">
              <Label>
                {t("liveRank", { game: nativeRankName })}
              </Label>
              <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
                {player.user_id != null ? (
                  <RankHistory userId={player.user_id} discipline={discipline} />
                ) : (
                  <RankHistory battleTag={primaryHandle} discipline={discipline} />
                )}
              </div>
            </div>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="player-notes">{t("adminNotes")}</Label>
            <Textarea
              id="player-notes"
              size="sm"
              value={form.notes}
              onChange={(event) => form.setNotes(event.target.value)}
              className="min-h-14"
              placeholder={t("notesPlaceholder")}
            />
          </div>
          {registration && statusOptions ? (
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="player-registration-status">
                  {t("registrationStatus")}
                </Label>
                <Select value={form.registrationStatus} onValueChange={form.setRegistrationStatus}>
                  <SelectTrigger id="player-registration-status" size="sm">
                    <SelectValue placeholder={t("selectRegistrationStatus")} />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.registration.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {t("systemOption", { name: option.name })}
                      </SelectItem>
                    ))}
                    {statusOptions.registration.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {t("customOption", { name: option.name })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="player-balancer-status">
                  {t("balancerStatus")}
                </Label>
                <Select
                  value={form.registrationBalancerStatus}
                  onValueChange={form.setRegistrationBalancerStatus}
                >
                  <SelectTrigger id="player-balancer-status" size="sm">
                    <SelectValue placeholder={t("selectBalancerStatus")} />
                  </SelectTrigger>
                  <SelectContent>
                    {form.registrationBalancerStatus === "ready" ||
                    form.registrationBalancerStatus === "incomplete" ? (
                      <SelectItem value={form.registrationBalancerStatus} disabled>
                        {t("computedOption", {
                          status:
                            form.registrationBalancerStatus === "ready" ? t("ready") : t("incomplete")
                        })}
                      </SelectItem>
                    ) : null}
                    {statusOptions.balancer.system
                      .filter((option) => option.value !== "ready" && option.value !== "incomplete")
                      .map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {t("systemOption", { name: option.name })}
                        </SelectItem>
                      ))}
                    {statusOptions.balancer.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {t("customOption", { name: option.name })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-label text-[color:var(--aqt-fg-dim)]">
                    {t("statusHint")}
                  </p>
                  {form.registrationBalancerStatus !== "ready" ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="accent"
                      className="shrink-0"
                      disabled={saving}
                      onClick={form.handleMoveToReady}
                      title={t("moveToReadyHint")}
                    >
                      <CheckCircle2 aria-hidden />
                      {t("moveToReady")}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <SheetFooter variant="panel" className="sm:justify-between">
          <div className="text-label text-[color:var(--aqt-fg-dim)]">
            {t("footerHint")}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              onClick={form.handleSave}
              disabled={saving}
              size="sm"
            >
              <Save className="mr-1 h-3.5 w-3.5" />
              {tCommon("save")}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
