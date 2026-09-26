"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { notify } from "@/lib/notify";
import { formatShortfall, type SlotLabelTranslator } from "@/lib/registration/team-shortfall";
import {
  getRegistrationTeamStatus,
  REGISTRATION_TEAM_STATUS_TONE,
} from "@/lib/registration/team-tone";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import { cn } from "@/lib/utils";
import type { RegistrationTeam } from "@/types/registration-team.types";

interface MyTeamHeaderProps {
  team: RegistrationTeam;
  /** Accepted starters and the places they are counted against. */
  starterCount: number;
  starterCapacity: number;
  locked: boolean;
  canEditRoster: boolean;
  /** Any roster write in flight, from the card's own pending set. */
  busy: boolean;
  /** The crest is only writable while the roster still is: the server refuses a
   *  terminal or already-exported team with `team_not_forming` /
   *  `team_already_exported`, so offering the control would be a dead end. */
  logoEditable: boolean;
  logoBusy: boolean;
  tSlot: SlotLabelTranslator;
  onRename: (name: string) => void;
  onUploadLogo: (file: File) => void;
  onDeleteLogo: () => void;
}

/** Crest, name (editable in place by staff), roster counters and status chips. */
export default function MyTeamHeader({
  team,
  starterCount,
  starterCapacity,
  locked,
  canEditRoster,
  busy,
  logoEditable,
  logoBusy,
  tSlot,
  onRename,
  onUploadLogo,
  onDeleteLogo,
}: Readonly<MyTeamHeaderProps>) {
  const t = useTranslations("registrationTeams");
  const [draftName, setDraftName] = useState(team.name);
  /** The name this draft was seeded from. A rename that lands from anywhere
   *  (this captain, a co-manager, an organizer) reseeds the field during
   *  render — an effect would render the stale name for one frame first. */
  const [seededName, setSeededName] = useState(team.name);

  if (seededName !== team.name) {
    setSeededName(team.name);
    setDraftName(team.name);
  }

  const status = getRegistrationTeamStatus(team);

  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <EditableAvatar
          src={team.image_url}
          name={team.name}
          size={44}
          shape="rounded"
          editable={logoEditable}
          busy={logoBusy}
          onSelectFile={onUploadLogo}
          onDelete={team.image_url ? onDeleteLogo : undefined}
          maxSizeBytes={MAX_AVATAR_BYTES}
          onError={(message) => notify.error(message)}
          labels={{
            change: t("create.logoChange"),
            upload: t("create.logoUpload"),
            edit: t("create.logoEdit"),
            drop: t("create.logoDrop"),
            remove: t("create.logoRemove"),
            unsupportedType: t("create.logoUnsupported"),
            tooLarge: t("create.logoTooLarge", {
              mb: Math.round(MAX_AVATAR_BYTES / (1024 * 1024)),
            }),
          }}
        />
        <div className="grid min-w-0 gap-0.5">
          {canEditRoster ? (
            <form
              className="flex min-w-0 items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (draftName.trim() && draftName.trim() !== team.name) {
                  onRename(draftName);
                }
              }}
            >
              <Input
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
                aria-label={t("rename.save")}
                className="h-8 min-w-0"
              />
              <Button
                type="submit"
                size="sm"
                disabled={busy || draftName.trim() === team.name || !draftName.trim()}
              >
                {t("rename.save")}
              </Button>
            </form>
          ) : (
            <h3 className="truncate text-base font-semibold">{team.name}</h3>
          )}
          <p className="text-xs text-[color:var(--aqt-fg-muted)]">
            {t("myCard.rosterCount", { filled: starterCount, total: starterCapacity })}
          </p>
          <p className="text-xs text-[color:var(--aqt-fg-muted)]">
            {team.is_complete
              ? t("list.complete")
              : t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}
          </p>
          {typeof team.checked_in_count === "number" && (team.check_in_total ?? 0) > 0 && (
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("checkIn.counts", {
                done: team.checked_in_count,
                total: team.check_in_total ?? 0,
              })}
            </p>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        {locked && (
          <span className="rounded-full border border-[color:var(--aqt-border)] px-2.5 py-0.5 text-xs">
            {t("lock.locked")}
          </span>
        )}
        {team.subscription_covered && (
          <span className="rounded-full border border-[color:var(--aqt-teal)]/40 px-2.5 py-0.5 text-xs text-[color:var(--aqt-teal)]">
            {t("cover.covered")}
          </span>
        )}
        {team.admission && team.admission !== "pending" && (
          <span className="rounded-full border border-[color:var(--aqt-border)] px-2.5 py-0.5 text-xs">
            {t(`admission.${team.admission}`)}
          </span>
        )}
        <span
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-xs font-medium",
            REGISTRATION_TEAM_STATUS_TONE[status]
          )}
        >
          {t(`status.${status}`)}
        </span>
      </div>
    </header>
  );
}
