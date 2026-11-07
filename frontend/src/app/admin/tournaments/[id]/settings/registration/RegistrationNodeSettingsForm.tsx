"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { NumberInput } from "@/components/ui/number-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { isSignUpOpen } from "@/lib/tournament/flow-nodes";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";
import { useTabAccess } from "../../sub-tabs";
import { useRegistrationNodeConfig } from "../useRegistrationNodeConfig";

/**
 * How one registration node takes entries: auto-approval, late sign-up, required check-in and the announced capacity.
 * Saved with the node's config (`PUT /admin/tournaments/{id}/flow`), so the page and a flow inspector can embed it as it is.
 * Remount it per node (`key={node.id}`).
 */
export function RegistrationNodeSettingsForm({
  tournament,
  node
}: Readonly<{ tournament: Tournament; node: TournamentFlowNode }>) {
  const t = useTranslations("registrationFormAdmin.page");
  const tStatus = useTranslations("registrationFormAdmin.status");
  const ids = useId();
  const disabled = !useTabAccess(tournament).canUpdateTournament;
  const { form, patch, dirty, summary, saving, save, discard, error } = useRegistrationNodeConfig(tournament.id, node);
  if (!form) return null;

  const hasEnd = node.schedule.some((entry) => entry.phase === "open" && entry.ends_at);

  return (
    <>
      <div className="flex flex-col gap-4">
        <SettingGroup id="status" title={tStatus("title")}>
          {/* Derived, not editable: openness is the node's status inside its sign-up window. Closed is the absence of the pill. */}
          <SettingRow label={tStatus("acceptLabel")} hint={tStatus("scheduleHint")}>
            {isSignUpOpen(node) ? <StatusPill tone="success">{tStatus("stateOpen")}</StatusPill> : null}
          </SettingRow>
          <SettingRow
            htmlFor={`${ids}-auto-approve`}
            label={tStatus("autoApproveLabel")}
            hint={tStatus("autoApproveHint")}
          >
            <Switch
              id={`${ids}-auto-approve`}
              checked={form.auto_approve}
              disabled={disabled}
              onCheckedChange={(next) => patch({ auto_approve: next })}
            />
          </SettingRow>
          <SettingRow
            htmlFor={`${ids}-allow-late`}
            label={tStatus("late")}
            hint={
              <>
                {tStatus("lateHint")}
                {!hasEnd && <span className="mt-0.5 block text-warning">{tStatus("noEnd")}</span>}
              </>
            }
          >
            <Switch
              id={`${ids}-allow-late`}
              checked={form.allow_late_registration}
              disabled={disabled}
              onCheckedChange={(next) => patch({ allow_late_registration: next })}
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-check-in`} label={tStatus("checkInLabel")} hint={tStatus("checkInHint")}>
            <Switch
              id={`${ids}-check-in`}
              checked={form.check_in}
              disabled={disabled}
              onCheckedChange={(next) => patch({ check_in: next })}
            />
          </SettingRow>
        </SettingGroup>

        <SettingGroup id="intake" title={t("intake.title")}>
          <SettingRow htmlFor={`${ids}-intake`} label={t("intake.label")} hint={t("intake.hint")}>
            <Select
              value={form.intake}
              disabled={disabled}
              onValueChange={(next) => patch({ intake: next as "solo" | "team" })}
            >
              <SelectTrigger id={`${ids}-intake`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="solo">{t("intake.solo")}</SelectItem>
                <SelectItem value="team">{t("intake.team")}</SelectItem>
              </SelectContent>
            </Select>
          </SettingRow>
        </SettingGroup>

        <SettingGroup id="capacity" title={t("capacity.title")}>
          <SettingRow
            htmlFor={`${ids}-max-participants`}
            label={t("display.maxParticipants")}
            hint={t("display.maxParticipantsHint")}
          >
            <NumberInput
              id={`${ids}-max-participants`}
              integer
              min={0}
              value={form.max_participants}
              disabled={disabled}
              onValueChange={(next) => patch({ max_participants: next })}
              size="sm"
              className="w-24"
            />
          </SettingRow>
        </SettingGroup>
      </div>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
