"use client";

import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { notify } from "@/lib/notify";
import { buildInviteLink } from "@/lib/registration/invite-link";
import { cn } from "@/lib/utils";

import type { MyTeamInviteController } from "./useMyTeamInvite";

const OPTION_CLASS =
  "block rounded-lg border px-3 py-1.5 text-sm transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--aqt-teal)]";
const OPTION_SELECTED_CLASS =
  "border-[color:var(--aqt-accent)] bg-[color:color-mix(in_srgb,var(--aqt-accent)_12%,transparent)]";
const OPTION_IDLE_CLASS = "border-[color:var(--aqt-border)] hover:bg-muted/40";
const OPTION_LABEL_CLASS =
  "block cursor-pointer active:scale-[0.96] transition-transform duration-150 ease-out";

interface MyTeamInviteDialogProps {
  invite: MyTeamInviteController;
  /** Derived, not synced: a roster that freezes while the dialog is open
   *  (exported, rejected, locked, window closed) closes it, because every
   *  write it can still submit is one the server now refuses. */
  canEditRoster: boolean;
  /** Whether the bench can still take one more player. */
  benchOpen: boolean;
  /** Any roster write in flight, from the card's own pending set. */
  busy: boolean;
  slotLabel: (code: string) => string;
}

export default function MyTeamInviteDialog({
  invite,
  canEditRoster,
  benchOpen,
  busy,
  slotLabel,
}: Readonly<MyTeamInviteDialogProps>) {
  const t = useTranslations("registrationTeams");
  const tCommon = useTranslations("common");
  const { issuedToken } = invite;
  const searchRef = useRef<HTMLInputElement>(null);

  return (
    <Dialog open={invite.open && canEditRoster} onOpenChange={invite.setOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogTitle>{t("invite.title")}</DialogTitle>

        {issuedToken ? (
          <div className="grid gap-2">
            <p className="text-sm font-medium">{t("invite.tokenTitle")}</p>
            <p className="text-xs text-warning">{t("invite.tokenHint")}</p>
            {/* The link, not the bare token: the token is a credential, not an
                instruction, and a recipient handed one had nowhere to put it. */}
            <code className="block overflow-x-auto rounded-lg border border-[color:var(--aqt-border)] bg-muted/30 px-3 py-2 text-xs">
              {buildInviteLink(issuedToken)}
            </code>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(buildInviteLink(issuedToken));
                notify.success(t("invite.copied"));
              }}
            >
              <Copy className="size-4" aria-hidden />
              {t("invite.copy")}
            </Button>
          </div>
        ) : (
          <div className="grid gap-3">
            {/* Two named modes, not one dialog that silently becomes a link
                when nobody is selected: the two invites differ in who can use
                them, and that choice must be made on purpose. */}
            <fieldset className="grid gap-1.5">
              <legend className="text-sm font-medium">{t("invite.modeLabel")}</legend>
              <div className="flex flex-wrap gap-2">
                {(["link", "targeted"] as const).map((mode) => (
                  <label key={mode} className={OPTION_LABEL_CLASS}>
                    <input
                      type="radio"
                      name="invite-mode"
                      value={mode}
                      checked={invite.mode === mode}
                      onChange={() => invite.selectMode(mode)}
                      className="peer sr-only"
                    />
                    <span
                      className={cn(
                        OPTION_CLASS,
                        invite.mode === mode ? OPTION_SELECTED_CLASS : OPTION_IDLE_CLASS
                      )}
                    >
                      {mode === "link" ? t("invite.modeLink") : t("invite.modeAccount")}
                    </span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {invite.mode === "link" ? t("invite.modeLinkHint") : t("invite.modeAccountHint")}
              </p>
            </fieldset>

            <fieldset className="grid gap-1.5">
              <legend className="text-sm font-medium">{t("invite.slotLabel")}</legend>
              <div className="flex flex-wrap gap-2">
                {invite.selectableSlots.map((code) => {
                  const selected = invite.slot === code;
                  return (
                    <label key={code} className={OPTION_LABEL_CLASS}>
                      <input
                        type="radio"
                        name="invite-slot"
                        value={code}
                        checked={selected}
                        onChange={() => invite.setSlot(code)}
                        className="peer sr-only"
                      />
                      <span
                        className={cn(
                          OPTION_CLASS,
                          selected ? OPTION_SELECTED_CLASS : OPTION_IDLE_CLASS
                        )}
                      >
                        {slotLabel(code)}
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            {benchOpen && (
              <Label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={invite.substitute}
                  onCheckedChange={(checked) => invite.toggleSubstitute(checked === true)}
                />
                {t("invite.substituteLabel")}
              </Label>
            )}

            {invite.mode === "targeted" && (
              <div className="grid gap-1.5">
                <span className="text-sm font-medium">{t("picker.label")}</span>
                <Input
                  ref={searchRef}
                  value={invite.search}
                  onChange={(event) => invite.setSearch(event.target.value)}
                  placeholder={t("picker.search")}
                  aria-label={t("picker.search")}
                />
                {invite.targetAgent && (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{t("picker.selected", { name: invite.targetAgent.battle_tag })}</span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => invite.setTargetRegistrationId(null)}
                    >
                      {t("picker.clear")}
                    </Button>
                  </div>
                )}
                {/* An empty roster of free agents and an empty search result are
                    different dead ends: one waits for registrations, the other
                    only needs a different query. */}
                {invite.agentsError ? (
                  /* A failed read is not an empty pool: one says "nobody to
                     recruit", the other only needs the request again. */
                  <p
                    role="alert"
                    className="flex flex-wrap items-center gap-2 text-xs text-[color:var(--aqt-rose)]"
                  >
                    {t("picker.loadError")}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={invite.retryAgents}
                    >
                      {tCommon("retry")}
                    </Button>
                  </p>
                ) : null}
                {!invite.agentsLoading && !invite.agentsError && invite.freeAgentCount === 0 && (
                  <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("picker.empty")}</p>
                )}
                {invite.freeAgentCount > 0 && invite.matchingAgents.length === 0 && (
                  <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("picker.noMatch")}</p>
                )}
                {invite.matchingAgents.length > 0 && (
                  <fieldset>
                    <legend className="sr-only">{t("picker.label")}</legend>
                    <ul className="grid max-h-48 gap-1 overflow-y-auto">
                      {invite.matchingAgents.map((agent) => {
                        const selected = invite.targetRegistrationId === agent.registration_id;
                        return (
                          <li key={agent.registration_id}>
                            <label className={OPTION_LABEL_CLASS}>
                              <input
                                type="radio"
                                name="invite-target-agent"
                                value={agent.registration_id}
                                checked={selected}
                                onChange={() =>
                                  invite.setTargetRegistrationId(agent.registration_id)
                                }
                                className="peer sr-only"
                              />
                              <span
                                className={cn(
                                  "flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm transition-colors",
                                  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--aqt-teal)]",
                                  selected ? OPTION_SELECTED_CLASS : OPTION_IDLE_CLASS
                                )}
                              >
                                <span className="truncate">{agent.battle_tag}</span>
                                {/* Roles on the row: the captain is filling one specific
                                    slot and should spot a tank without opening a profile. */}
                                {agent.roles.map((role) => (
                                  <span
                                    key={role}
                                    className="rounded-full border border-[color:var(--aqt-border-2)] px-2 py-0.5 text-label text-[color:var(--aqt-fg-muted)]"
                                  >
                                    {slotLabel(role)}
                                  </span>
                                ))}
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </fieldset>
                )}
              </div>
            )}

            {invite.validation && (
              <p role="alert" className="text-xs text-[color:var(--aqt-rose)]">
                {invite.validation}
              </p>
            )}
            <Button
              type="button"
              /* Enabled until the request starts: a disabled submit hides what
                 is missing, so the unmade choice is named instead. */
              disabled={busy || !invite.slot}
              onClick={() => {
                if (!invite.submit()) searchRef.current?.focus();
              }}
            >
              {t("invite.submit")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
