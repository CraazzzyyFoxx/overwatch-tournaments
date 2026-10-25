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
  onRemove?: (playerId: number) => void;
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
  onRemove,
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
        className="w-full bg-popover/95 backdrop-blur-xl sm:max-w-[640px] [&>button:last-child]:right-4 [&>button:last-child]:top-4 [&>button:last-child]:z-20 [&>button:last-child]:flex [&>button:last-child]:h-8 [&>button:last-child]:w-8 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>button:last-child]:rounded-lg [&>button:last-child]:border [&>button:last-child]:border-[color:var(--aqt-border-2)] [&>button:last-child]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:p-0 [&>button:last-child]:text-[color:var(--aqt-fg-muted)] [&>button:last-child]:backdrop-blur-sm [&>button:last-child]:hover:bg-[color:var(--aqt-overlay-3)] [&>button:last-child]:hover:text-[color:var(--aqt-fg)] [&>button:last-child]:data-[state=open]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:data-[state=open]:text-[color:var(--aqt-fg-muted)]"
      >
        <SheetHeader
          variant="panel"
          className={cn(
            "px-4 pb-2.5 pt-3 sm:px-5 sm:pb-3 sm:pt-3.5",
            onRemove ? "pr-20 sm:pr-24" : "pr-14 sm:pr-16"
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle className="text-base font-semibold tracking-tight text-[color:var(--aqt-fg)]">
              {primaryHandle}
            </SheetTitle>
            <HandleCopyButton handle={primaryHandle} className="h-6 w-6" />
            {form.isFlex ? (
              <Badge className="h-5 border-emerald-400/25 bg-emerald-400/10 px-2 text-label text-emerald-200 hover:bg-emerald-400/10">
                {t("flex")}
              </Badge>
            ) : null}
          </div>
          <AdditionalHandleStrip additionalHandles={player.additional_handles} className="mt-1.5" />
          <SheetDescription className="text-xs text-[color:var(--aqt-fg-dim)]">
            {t("description")}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
          <div className="grid gap-2.5 lg:grid-cols-2">
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  {t("balancerStatus")}
                </span>
                {registration ? (
                  <StatusMetaBadge
                    meta={registration.balancer_status_meta}
                    className="h-5 text-label"
                  />
                ) : (
                  <Badge
                    className={cn(
                      "h-5 px-2 text-label",
                      computedReady
                        ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                        : "border-orange-400/25 bg-orange-400/10 text-orange-200"
                    )}
                  >
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
                    ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                    : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <Label
                    htmlFor="is-flex"
                    className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]"
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
              <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
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
                className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]"
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
              <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
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
            <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">{t("adminNotes")}</Label>
            <Textarea
              value={form.notes}
              onChange={(event) => form.setNotes(event.target.value)}
              className="min-h-14 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-1.5 text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-faint)]"
              placeholder={t("notesPlaceholder")}
            />
          </div>
          {registration && statusOptions ? (
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  {t("registrationStatus")}
                </Label>
                <Select value={form.registrationStatus} onValueChange={form.setRegistrationStatus}>
                  <SelectTrigger size="sm">
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
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  {t("balancerStatus")}
                </Label>
                <Select
                  value={form.registrationBalancerStatus}
                  onValueChange={form.setRegistrationBalancerStatus}
                >
                  <SelectTrigger size="sm">
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
                      size="sm"
                      variant="outline"
                      className="h-6 shrink-0 gap-1 whitespace-nowrap border-emerald-500/30 bg-emerald-500/10 px-2 text-emerald-200 hover:bg-emerald-500/20 hover:text-emerald-100"
                      disabled={saving}
                      onClick={form.handleMoveToReady}
                      title={t("moveToReadyHint")}
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      {t("moveToReady")}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <SheetFooter className="shrink-0 border-t border-[color:var(--aqt-border)] px-4 py-2.5 sm:justify-between sm:space-x-0 sm:px-5">
          <div className="text-label text-[color:var(--aqt-fg-dim)]">
            {t("footerHint")}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-3 text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              onClick={() => onOpenChange(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              onClick={form.handleSave}
              disabled={saving}
              size="sm"
              className="bg-primary px-3 text-primary-foreground hover:bg-primary/90"
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
