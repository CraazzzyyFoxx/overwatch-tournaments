"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, Send, UserPlus } from "lucide-react";

import { postModeOf, signupPostOf } from "@/app/balancer/mix/PickupMixHeader";
import { CAPTION_CLASS, CARD_TITLE_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { cn } from "@/lib/utils";
import type { CustomGame } from "@/services/custom-game.service";

/**
 * What a host does with a mix that has never played, in order, in place of the
 * empty matchup inside the lobby card. Each step ticks itself off from the
 * mix's own state, so a host who came back halfway sees where they stopped.
 *
 * The first open step is the current one and carries the screen's one solid
 * button; the steps after it wait, dimmed. The Discord announcement is
 * optional, so it never holds the balance step back: once players are in, an
 * unannounced mix keeps a quiet Post button on that step.
 */
export function PickupGettingStarted({
  game,
  onOpenPool,
  onPostSignup,
  posting,
  balanceAction
}: Readonly<{
  game: CustomGame;
  onOpenPool: () => void;
  /** Omitted -- the Discord step is not offered. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  posting: boolean;
  /** The lobby's own Balance (or Draft) control, handed in by `PickupTeamsPanel`: the last step's action. */
  balanceAction: ReactNode;
}>) {
  const t = useTranslations("mixes.start");
  const ts = useTranslations("mixes.self");
  const playerCount = (game.players ?? []).length;
  const gathered = playerCount > 0;
  const postStatus = signupPostOf(game)?.status;
  const announced = postStatus === "posted" || postStatus === "pending";
  const hasChannel = game.settings.workspace_discord_channel_id != null;
  const draft = game.team_formation === "draft";

  return (
    <section aria-label={t("title")} className="flex flex-col gap-3 px-4 py-3.5">
      <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>
      <ol className="flex flex-col gap-3">
        <Step
          number={1}
          state={gathered ? "done" : "current"}
          title={t("players")}
          detail={gathered ? t("playersDone", { count: playerCount }) : t("playersHint")}
          action={
            <Button type="button" size="sm" onClick={onOpenPool}>
              <UserPlus className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("addPlayers")}
            </Button>
          }
        />
        {onPostSignup ? (
          <Step
            number={2}
            state={announced ? "done" : gathered ? "open" : "later"}
            title={t("discord")}
            detail={announced ? t("discordDone") : hasChannel ? t("discordHint") : ts("noChannel")}
            action={
              hasChannel ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={posting}
                  onClick={() => onPostSignup(postModeOf(game.self_signup))}
                >
                  {posting ? (
                    <Spinner className="mr-1.5 size-3.5" />
                  ) : (
                    <Send className="mr-1.5 size-3.5" aria-hidden="true" />
                  )}
                  {game.self_signup === "closed" ? ts("discord.openAndPost") : ts("discord.post")}
                </Button>
              ) : null
            }
          />
        ) : null}
        <Step
          number={onPostSignup ? 3 : 2}
          state={gathered ? "current" : "later"}
          title={t(draft ? "draft" : "balance")}
          detail={t(draft ? "draftHint" : "balanceHint")}
          action={balanceAction}
        />
      </ol>
    </section>
  );
}

/** `open`: an optional step before the current one, still actionable but not the next thing to do. */
type StepState = "done" | "current" | "open" | "later";

function Step({
  number,
  state,
  title,
  detail,
  action
}: Readonly<{ number: number; state: StepState; title: string; detail: string; action?: ReactNode }>) {
  if (state === "done") {
    return (
      <li className="flex items-center gap-3">
        <CheckCircle2 className="size-5 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden="true" />
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
          <span className="text-ui font-semibold text-[color:var(--aqt-fg-muted)]">{title}</span>
          <span className={CAPTION_CLASS}>· {detail}</span>
        </div>
      </li>
    );
  }
  const later = state === "later";
  return (
    <li className="flex flex-wrap items-start gap-3">
      <span
        aria-hidden="true"
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-[color:var(--aqt-border)] text-label font-semibold text-[color:var(--aqt-fg-muted)]"
      >
        {number}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div
          className={cn(
            "text-ui font-semibold",
            later ? "text-[color:var(--aqt-fg-dim)]" : "text-[color:var(--aqt-fg)]"
          )}
        >
          {title}
        </div>
        <p
          className={cn(
            "text-caption",
            later ? "text-[color:var(--aqt-fg-faint)]" : "text-[color:var(--aqt-fg-dim)]"
          )}
        >
          {detail}
        </p>
      </div>
      {!later && action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
    </li>
  );
}
