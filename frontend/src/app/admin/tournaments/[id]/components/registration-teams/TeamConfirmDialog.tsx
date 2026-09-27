"use client";

import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";

import type { PendingConfirm } from "./model";

/** What a confirmed rejection carries back: the reason its captain reads, and
 *  which of the two consequences the organizer chose. */
export interface RejectDecision {
  reason: string;
  withdrawMembers: boolean;
}

/**
 * The screen's one confirmation, with the strings — and, for a rejection, the
 * fields — of whichever act is open.
 *
 * One mount with a swapped intent rather than four near-identical dialogs whose
 * only difference was their words. The rejection fields live here because they
 * are only ever read by the confirm click directly below them.
 */
export function TeamConfirmDialog({
  confirm,
  busy,
  rejecting,
  inlineError,
  onOpenChange,
  onConfirm
}: Readonly<{
  confirm: PendingConfirm | null;
  busy: boolean;
  rejecting: boolean;
  /** The last refusal, rendered inside the dialog that caused it. */
  inlineError: ReactNode;
  onOpenChange: (open: boolean) => void;
  /** `null` for every act but a rejection, whose fields are asked for here. */
  onConfirm: (decision: RejectDecision | null) => void;
}>) {
  const t = useTranslations("registrationTeams");
  const reasonId = useId();

  const [withdrawMembers, setWithdrawMembers] = useState(false);
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  // A different act is being asked about, so the fields of the last one are not
  // its answer. Synced during render rather than in an effect: an effect would
  // commit one render with the previous act's reason already on screen.
  const [asked, setAsked] = useState(confirm);
  if (asked !== confirm) {
    setAsked(confirm);
    setWithdrawMembers(false);
    setReason("");
    setValidation(null);
  }

  let intent: ConfirmIntent;
  if (confirm?.kind === "export") {
    const label = confirm.teams.some((team) => team.exported_team_id != null)
      ? t("admin.reExport")
      : t("admin.exportSelected");
    intent = {
      title: label,
      confirmLabel: label,
      tone: "warning",
      description: (
        <div className="space-y-2">
          <p>{t("admin.exportConfirmHint")}</p>
          <ul className="max-h-48 list-inside list-disc overflow-y-auto">
            {confirm.teams.map((team) => (
              <li key={team.id}>{team.name}</li>
            ))}
          </ul>
          {inlineError}
        </div>
      )
    };
  } else if (confirm?.kind === "unlock") {
    intent = {
      title: `${t("admin.unlock")} — ${confirm.team.name}`,
      confirmLabel: t("admin.unlock"),
      tone: "warning",
      description: inlineError
    };
  } else if (confirm?.kind === "resetCap") {
    intent = {
      title: t("admin.resetCapConfirm", { team: confirm.team.name }),
      confirmLabel: t("admin.resetCap"),
      tone: "warning",
      description: inlineError
    };
  } else {
    intent = {
      title: t("admin.rejectConfirm", { team: confirm?.kind === "reject" ? confirm.team.name : "" }),
      // Never one neutral "Confirm": the button says which of the two
      // consequences below it is about to apply.
      confirmLabel: withdrawMembers ? t("admin.rejectAndWithdraw") : t("admin.rejectKeepPlayers"),
      tone: "danger",
      description: (
        <div className="space-y-3">
          <p>{t("admin.rejectConsequences")}</p>
          {inlineError}
          <fieldset disabled={rejecting}>
            <legend className="mb-2 text-sm font-medium">{t("admin.rejectConsequence")}</legend>
            <RadioGroup
              value={withdrawMembers ? "withdraw" : "preserve"}
              onValueChange={(value) => setWithdrawMembers(value === "withdraw")}
            >
              <Label className="flex items-start gap-2 text-sm font-normal">
                <RadioGroupItem value="preserve" className="mt-0.5" />
                {t("admin.rejectPreserve")}
              </Label>
              <Label className="flex items-start gap-2 text-sm font-normal">
                <RadioGroupItem value="withdraw" className="mt-0.5" />
                {t("admin.rejectWithdraw")}
              </Label>
            </RadioGroup>
          </fieldset>
          <Label className="grid gap-1.5 text-sm">
            {t("admin.rejectReason")}
            <Textarea
              id={reasonId}
              required
              maxLength={1000}
              disabled={rejecting}
              aria-invalid={!!validation}
              aria-describedby={validation ? `${reasonId}-error` : undefined}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
            />
          </Label>
          {validation && (
            <p id={`${reasonId}-error`} role="alert" className="text-sm text-danger">
              {validation}
            </p>
          )}
        </div>
      )
    };
  }

  return (
    <ConfirmDialog
      open={confirm != null}
      onOpenChange={onOpenChange}
      pending={busy}
      intent={intent}
      onConfirm={() => {
        if (!confirm) return;
        if (confirm.kind !== "reject") {
          onConfirm(null);
          return;
        }
        const trimmed = reason.trim();
        if (!trimmed) {
          setValidation(t("admin.rejectReasonRequired"));
          document.getElementById(reasonId)?.focus();
          return;
        }
        setValidation(null);
        onConfirm({ reason: trimmed, withdrawMembers });
      }}
    />
  );
}
