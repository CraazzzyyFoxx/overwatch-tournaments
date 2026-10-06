"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, Send, UserPlus } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { postModeOf, signupPostOf } from "@/app/balancer/mix/PickupMixHeader";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { CustomGame } from "@/services/custom-game.service";

/**
 * What a host does with a mix that has never played, in order, in place of
 * the empty matchup. Each step ticks itself off from the mix's own state, so
 * a host who came back halfway sees where they stopped.
 */
export function PickupGettingStarted({
  game,
  onOpenPool,
  onPostSignup,
  posting
}: Readonly<{
  game: CustomGame;
  onOpenPool: () => void;
  /** Omitted -- the Discord step is not offered. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  posting: boolean;
}>) {
  const t = useTranslations("mixes.start");
  const ts = useTranslations("mixes.self");
  const playerCount = (game.players ?? []).length;
  const postStatus = signupPostOf(game)?.status;
  const announced = postStatus === "posted" || postStatus === "pending";
  const hasChannel = game.settings.workspace_discord_channel_id != null;

  return (
    <section aria-label={t("title")} className={cn(PANEL_CLASS, "space-y-4 px-5 py-5")}>
      <span className={EYEBROW_CLASS}>{t("title")}</span>
      <ol className="space-y-4">
        <Step
          number={1}
          done={playerCount > 0}
          title={t("players")}
          hint={playerCount > 0 ? t("playersDone", { count: playerCount }) : t("playersHint")}
          action={
            <Button type="button" variant="outline" className="h-8" onClick={onOpenPool}>
              <UserPlus className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("addPlayers")}
            </Button>
          }
        />
        {onPostSignup ? (
          <Step
            number={2}
            done={announced}
            title={t("discord")}
            hint={announced ? t("discordDone") : hasChannel ? t("discordHint") : ts("noChannel")}
            action={
              hasChannel && !announced ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-8"
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
          done={false}
          title={t("balance")}
          hint={t("balanceHint")}
        />
      </ol>
    </section>
  );
}

function Step({
  number,
  done,
  title,
  hint,
  action
}: Readonly<{ number: number; done: boolean; title: string; hint: string; action?: ReactNode }>) {
  return (
    <li className="flex items-start gap-3" data-done={done}>
      {done ? (
        <CheckCircle2
          className="mt-0.5 size-5 shrink-0 text-[color:var(--aqt-teal)]"
          aria-hidden="true"
        />
      ) : (
        <span
          aria-hidden="true"
          className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-[color:var(--aqt-border)] text-label font-semibold text-[color:var(--aqt-fg-muted)]"
        >
          {number}
        </span>
      )}
      <div className="min-w-0 flex-1 space-y-0.5">
        <div
          className={cn(
            "text-sm font-semibold",
            done ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
          )}
        >
          {title}
        </div>
        <p className="text-caption text-[color:var(--aqt-fg-dim)]">{hint}</p>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </li>
  );
}
