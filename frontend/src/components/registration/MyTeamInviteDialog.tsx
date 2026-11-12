"use client";

import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef } from "react";

import { PersonLabel } from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { notify } from "@/lib/notify";
import { buildInviteLink } from "@/lib/registration/invite-link";
import { roleOf } from "@/lib/roster/role-ref";
import type { RoleOntology } from "@/lib/roster/ontology";

import type { MyTeamInviteController } from "./useMyTeamInvite";

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
  /** The owner game's scoped ontology, for a free agent's role glyphs; `null` while it loads. */
  ontology: RoleOntology | null;
  /** `false` in a one-role game: every slot is that role, so the invite asks none (`invite.slot` already holds it)
   *  and a free agent's role glyphs would repeat it on every row. */
  showsSlots: boolean;
}

export default function MyTeamInviteDialog({
  invite,
  canEditRoster,
  benchOpen,
  busy,
  slotLabel,
  ontology,
  showsSlots,
}: Readonly<MyTeamInviteDialogProps>) {
  const t = useTranslations("registrationTeams");
  const tCommon = useTranslations("common");
  const { issuedToken } = invite;
  const searchRef = useRef<HTMLInputElement>(null);
  const id = useId();

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
            <div className="grid gap-1.5">
              <p id={`${id}-mode`} className="text-sm font-medium">
                {t("invite.modeLabel")}
              </p>
              <RadioGroup
                aria-labelledby={`${id}-mode`}
                value={invite.mode}
                onValueChange={(mode) => invite.selectMode(mode as MyTeamInviteController["mode"])}
                className="flex flex-wrap gap-2"
              >
                {(["link", "targeted"] as const).map((mode) => (
                  <RadioGroupItem key={mode} value={mode} variant="card">
                    {mode === "link" ? t("invite.modeLink") : t("invite.modeAccount")}
                  </RadioGroupItem>
                ))}
              </RadioGroup>
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {invite.mode === "link" ? t("invite.modeLinkHint") : t("invite.modeAccountHint")}
              </p>
            </div>

            {showsSlots ? (
              <div className="grid gap-1.5">
                <p id={`${id}-slot`} className="text-sm font-medium">
                  {t("invite.slotLabel")}
                </p>
                <RadioGroup
                  aria-labelledby={`${id}-slot`}
                  value={invite.slot ?? ""}
                  onValueChange={invite.setSlot}
                  className="flex flex-wrap gap-2"
                >
                  {invite.selectableSlots.map((code) => (
                    <RadioGroupItem key={code} value={code} variant="card">
                      {slotLabel(code)}
                    </RadioGroupItem>
                  ))}
                </RadioGroup>
              </div>
            ) : null}

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
                    <span>{t("picker.selected", { name: invite.targetAgent.display.name })}</span>
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
                  <RadioGroup
                    aria-label={t("picker.label")}
                    value={invite.targetRegistrationId == null ? "" : String(invite.targetRegistrationId)}
                    onValueChange={(registrationId) =>
                      invite.setTargetRegistrationId(Number(registrationId))
                    }
                    className="max-h-48 gap-1 overflow-y-auto"
                  >
                    {invite.matchingAgents.map((agent) => (
                      <RadioGroupItem
                        key={agent.registration_id}
                        value={String(agent.registration_id)}
                        variant="card"
                        className="flex w-full flex-wrap items-center gap-2"
                      >
                        <PersonLabel display={agent.display} />
                        {/* Roles on the row: the captain is filling one specific
                            slot and should spot a tank without opening a profile. */}
                        {showsSlots &&
                          agent.roles.map((role) => (
                            <PlayerRoleIcon
                              key={`${role.dimension}:${role.role}`}
                              role={{ dimension: role.dimension, role: roleOf(role) }}
                              ontology={ontology}
                              label={slotLabel(roleOf(role))}
                              size={16}
                            />
                          ))}
                      </RadioGroupItem>
                    ))}
                  </RadioGroup>
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
