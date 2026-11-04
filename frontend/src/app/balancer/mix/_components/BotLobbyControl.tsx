"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Bot } from "lucide-react";

import {
  botLobbyMinutesLeft,
  initialRegion,
  type BotLobbyOptions
} from "@/app/balancer/mix/pickup-bot-lobby";
import { CAPTION_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import type { MixBotLobby } from "@/services/custom-game.service";

/**
 * The host's bot lobby for a LIVE match: a region and "Create lobby via bot" (the bot opens the in-game party and its
 * code lands in the lobby code), the minutes left until the bot leaves, and "Recreate" once it has. The bot leaves 15
 * minutes after creating the party whatever the match does, so the control says to start within that time.
 */
export function BotLobbyControl({
  options,
  botLobby
}: Readonly<{ options: BotLobbyOptions; botLobby: MixBotLobby | null | undefined }>) {
  const t = useTranslations("mixes.botLobby");
  const now = useMinuteClock();
  const [picked, setPicked] = useState<string | null>(null);
  const region = picked ?? initialRegion(options);

  const minutesLeft = botLobby != null && now != null ? botLobbyMinutesLeft(botLobby, now) : null;
  const expired = minutesLeft != null && minutesLeft <= 0;
  const open = botLobby != null && !expired;
  const regionName = (code: string) => {
    const key = `regions.${code}` as "regions.europe";
    return t.has(key) ? t(key) : code;
  };

  return (
    <div className="flex flex-col gap-2">
      {open ? null : (
        <div className="flex flex-wrap items-center gap-2">
          <Select value={region} onValueChange={setPicked} disabled={options.creating}>
            <SelectTrigger size="sm" className="w-auto" aria-label={t("region")}>
              <SelectValue>{regionName(region)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {options.regions.map((code) => (
                <SelectItem key={code} value={code}>
                  {regionName(code)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={options.creating}
            onClick={() => options.onCreate(region)}
          >
            {options.creating ? <Spinner className="mr-1.5 size-3.5" /> : <Bot className="mr-1.5 size-3.5" aria-hidden />}
            {botLobby != null ? t("recreate") : t("create")}
          </Button>
        </div>
      )}
      {expired ? (
        <p role="status" className="text-caption text-[color:var(--aqt-amber)]">
          {t("expired")}
        </p>
      ) : open && (botLobby.match_id != null || minutesLeft != null) ? (
        <p role="status" className={CAPTION_CLASS}>
          {botLobby.match_id != null ? t("matchSeen") : t("open", { minutes: minutesLeft ?? 0 })}
        </p>
      ) : null}
      {expired || botLobby?.match_id != null ? null : <p className={CAPTION_CLASS}>{t("startWithin")}</p>}
    </div>
  );
}
