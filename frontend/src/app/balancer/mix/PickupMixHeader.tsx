"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, Send, Trash2, UserCog, UserPlus } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CustomGame, MixSelfSignup } from "@/services/custom-game.service";

/** The three signup modes, in the order a host widens access. */
const SELF_SIGNUP_OPTIONS: readonly MixSelfSignup[] = ["closed", "pool", "benched"];

type PickupMixHeaderProps = {
  /** Host or co-host, and not-terminal -- gates every write action in this header. */
  canWrite: boolean;
  game: CustomGame | undefined;
  gameLoading: boolean;
  onOpenPool: () => void;
  onOpenAccess: () => void;
  /** Workspace admin (or superuser) -- gates the irreversible hard delete,
   * a stronger grant than the host-or-co-host `canWrite` above. */
  canDelete?: boolean;
  deleting?: boolean;
  onDeleteMix?: () => void;
  /** Omitted -- the self-service row is not offered at all. */
  onSetSelfService?: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
  savingSelfService?: boolean;
  /** Omitted -- no "open signup in Discord" button. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  postingSignup?: boolean;
};

/**
 * The mix this screen is open on: the way back to the list, its name and id,
 * and the one write a host does before touching a lineup -- pull more
 * players in. One line instead of three: the back link, the identity and the
 * write used to stack as separate rows and read as three unrelated pieces of
 * chrome instead of one header.
 *
 * Boxed in the same `PANEL_CLASS` card every other block on this screen
 * uses (the verdict pills, the team card, the record-result bar) -- bare, it
 * was the only unbordered row on the page, so the gap `Add players` leaves
 * between itself and the title read as an accident instead of a header's own
 * padding.
 *
 * Which mix this is comes from the route, not from state this header owns --
 * switching to another one, or starting a new one, happens on the list at
 * `/balancer/mix`. This is the only place the mix's name and number sit
 * together.
 */
export function PickupMixHeader({
  canWrite,
  game,
  gameLoading,
  onOpenPool,
  onOpenAccess,
  canDelete = false,
  deleting = false,
  onDeleteMix,
  onSetSelfService,
  savingSelfService = false,
  onPostSignup,
  postingSignup = false,
}: Readonly<PickupMixHeaderProps>) {
  const t = useTranslations("mixes.self");
  const [deleteOpen, setDeleteOpen] = useState(false);
  // The workspace's channel is the only target a mix has -- with none, the
  // signup card has nowhere to go. Unlike the matchup post (which simply is
  // not offered), this one stays visible and says why: a host who opens
  // signup expects the Discord button to be there, and "missing" reads as a
  // bug where "disabled, because there is no channel" reads as an answer.
  const hasChannel = game?.settings.workspace_discord_channel_id != null;

  return (
    <div className={cn(PANEL_CLASS, "flex flex-wrap items-center gap-3 px-4 py-3")}>
      <Link
        href="/balancer/mix"
        className="flex shrink-0 items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)] transition-colors hover:text-[color:var(--aqt-fg-muted)]"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        Mixes
      </Link>

      <span aria-hidden="true" className="h-5 w-px shrink-0 bg-[color:var(--aqt-border)]" />

      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <span className={EYEBROW_CLASS}>Mix</span>
        <h1 className="min-w-0 truncate font-display text-xl font-bold tracking-[-0.01em] text-[color:var(--aqt-fg)]">
          {game?.name ?? (gameLoading ? "\u2026" : "No mix yet")}
        </h1>
        {game ? (
          <span className="shrink-0 text-caption font-semibold text-[color:var(--aqt-fg-dim)]">
            {`#${game.id}`}
          </span>
        ) : null}
      </div>

      {canWrite ? (
        <Button
          type="button"
          variant="outline"
          className="h-9 shrink-0"
          disabled={game == null}
          onClick={onOpenPool}
        >
          <UserPlus className="mr-1.5 size-3.5" aria-hidden="true" />
          Add players
        </Button>
      ) : null}

      {canWrite ? (
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0"
          disabled={game == null}
          onClick={onOpenAccess}
          aria-label="Manage access"
        >
          <UserCog className="size-3.5" aria-hidden="true" />
        </Button>
      ) : null}

      {canDelete && onDeleteMix ? (
        <>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-9 w-9 shrink-0 text-[color:var(--aqt-fg-muted)] hover:border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] hover:text-rose-200"
            disabled={game == null || deleting}
            aria-label="Delete mix"
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
          </Button>
          <ConfirmDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            intent={{
              title: "Delete this mix?",
              description: `Permanently removes ${game?.name ?? "this mix"} and every match it recorded. This cannot be undone -- unlike Close, there is no way back to it afterwards.`,
              confirmLabel: "Delete permanently",
              tone: "danger"
            }}
            pending={deleting}
            onConfirm={() => {
              setDeleteOpen(false);
              onDeleteMix?.();
            }}
          />
        </>
      ) : null}

      {canWrite && game != null && onSetSelfService ? (
        <div className="flex w-full flex-wrap items-center gap-2.5 border-t border-[color:var(--aqt-border)] pt-3">
          <span className={EYEBROW_CLASS}>{t("signupLabel")}</span>

          <div role="radiogroup" aria-label={t("signupLabel")} className="flex items-center gap-1">
            {SELF_SIGNUP_OPTIONS.map((option) => {
              const selected = game.self_signup === option;
              return (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={savingSelfService}
                  onClick={() => onSetSelfService({ self_signup: option })}
                  className={cn(
                    "rounded-lg border px-2.5 py-1 text-caption font-semibold transition-colors",
                    selected
                      ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)]"
                      : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-3)]",
                    "disabled:cursor-default disabled:opacity-60",
                  )}
                >
                  {t(`signup.${option}`)}
                </button>
              );
            })}
          </div>

          <span aria-hidden="true" className="h-5 w-px shrink-0 bg-[color:var(--aqt-border)]" />

          <div className="flex items-center gap-2">
            <Switch
              checked={game.self_role_edit}
              disabled={savingSelfService}
              aria-label={t("roleEdit")}
              onCheckedChange={(checked) => onSetSelfService({ self_role_edit: checked })}
            />
            <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("roleEdit")}</span>
          </div>

          {onPostSignup ? (
            <Button
              type="button"
              variant="outline"
              className="ml-auto h-9 shrink-0"
              disabled={!hasChannel || postingSignup}
              title={hasChannel ? undefined : t("noChannel")}
              // A closed mix has no mode to post yet, and the card's whole point
              // is to open signup -- so posting it from `closed` opens the pool,
              // the mode a host picks in every other case.
              onClick={() => onPostSignup(game.self_signup === "benched" ? "benched" : "pool")}
            >
              <Send className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("openInDiscord")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
