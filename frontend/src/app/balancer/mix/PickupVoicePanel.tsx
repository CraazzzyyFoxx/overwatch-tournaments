"use client";

import { useTranslations } from "next-intl";

import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  EYEBROW_CLASS,
  lobbyLetter,
} from "@/app/balancer/mix/pickup-chrome";
import { busyVoices, voiceBlocker, voicePatch, type BusyVoice } from "@/app/balancer/mix/pickup-voice";
import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type {
  CustomGame,
  MixVoiceChannel,
  MixVoiceOptions,
  MixVoicePatch,
  MixVoiceReport,
  MixVoiceStatus,
} from "@/services/custom-game.service";

/** Radix refuses an empty item value, and a channel id is always digits. */
const NONE = "none";

type PickupVoicePanelProps = {
  game: CustomGame;
  /** Every mix of the workspace: which team voices the other open ones hold. */
  games: CustomGame[];
  options: MixVoiceOptions | undefined;
  optionsLoading: boolean;
  saving: boolean;
  moving: boolean;
  returning: boolean;
  report: MixVoiceReport | undefined;
  onSave: (patch: MixVoicePatch) => void;
  onMove: (lobbyIndex: number | null) => void;
  onReturn: (lobbyIndex: number | null) => void;
};

type VoiceSelectProps = {
  label: string;
  ariaLabel: string;
  value: string | null;
  channels: MixVoiceChannel[];
  busy: Map<string, BusyVoice>;
  disabled: boolean;
  onChange: (channelId: string | null) => void;
};

/**
 * One voice pick. Everything a host needs to judge a voice is on its own row:
 * whether another mix is already in it, and whether the bot can use it at all.
 */
function VoiceSelect({
  label,
  ariaLabel,
  value,
  channels,
  busy,
  disabled,
  onChange,
}: Readonly<VoiceSelectProps>) {
  const t = useTranslations("mixes.voice");
  // A voice the mix saved and the category no longer lists -- moved out, or
  // renamed into a general one. Dropping it from the list would silently clear
  // a pick the host made, so it stays, labelled for what it is.
  const outside = value != null && !channels.some((channel) => channel.id === value);

  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1">
      <span className={EYEBROW_CLASS}>{label}</span>
      <Select
        value={value ?? NONE}
        disabled={disabled}
        onValueChange={(next) => onChange(next === NONE ? null : next)}
      >
        <SelectTrigger aria-label={ariaLabel} className="h-9 min-w-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{t("none")}</SelectItem>
          {outside && value != null ? (
            <SelectItem value={value}>{t("outsideCategory")}</SelectItem>
          ) : null}
          {channels.map((channel) => {
            const taken = busy.get(channel.id);
            return (
              <SelectItem
                key={channel.id}
                value={channel.id}
                // Discord would refuse the move: no point letting it be picked.
                disabled={(channel.missing_permissions ?? []).length > 0}
              >
                {channel.name}
                {taken ? (
                  <span className={cn(CAPTION_CLASS, "ml-1.5")}>
                    {t("busy", { mix: taken.gameName, letter: lobbyLetter(taken.lobbyIndex) })}
                  </span>
                ) : null}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
    </label>
  );
}

/**
 * Where this mix's players sit in Discord: one general voice everybody waits
 * in, and two team voices per lobby the bot moves them between.
 *
 * The picks are the mix's own, but what may be picked is the workspace's: only
 * the voices of its configured category (`Settings → Discord`) are listed, and
 * a permission the bot lacks disables the voice and the move alike -- the
 * server would refuse that move anyway, so the refusal is said here, before the
 * click, with the missing permission named.
 */
export function PickupVoicePanel({
  game,
  games,
  options,
  optionsLoading,
  saving,
  moving,
  returning,
  report,
  onSave,
  onMove,
  onReturn,
}: Readonly<PickupVoicePanelProps>) {
  const t = useTranslations("mixes.voice");

  const picked = [
    game.general_voice_channel_id,
    ...game.lobbies.flatMap((lobby) => [lobby.team1_voice_channel_id, lobby.team2_voice_channel_id]),
  ];
  const blocker = voiceBlocker(options, picked);
  const busy = busyVoices(games, game.id);
  const multi = game.lobby_count > 1;
  const runDisabled = moving || returning || blocker.length > 0;
  // A non-moved result is the only one worth naming: who moved is the count.
  const failures = (report?.results ?? []).filter((row) => row.status !== "moved");
  const statuses = [...new Set(failures.map((row) => row.status))] as Exclude<
    MixVoiceStatus,
    "moved"
  >[];

  return (
    <section className={cn(PANEL_CLASS, "flex flex-col gap-3 px-4 py-3.5")}>
      <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>

      {options == null ? null : options.category_id == null ? (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("notConfigured")}</p>
      ) : (
        <>
          {options.error ? <p className="text-caption text-amber-200">{t("unreachable")}</p> : null}

          {blocker.length > 0 ? (
            <Alert variant="destructive">
              <AlertDescription>
                {t("missing", { permissions: blocker.map((name) => t(`permission.${name}`)).join(", ") })}
              </AlertDescription>
            </Alert>
          ) : null}

          <VoiceSelect
            label={t("general")}
            ariaLabel={t("general")}
            value={game.general_voice_channel_id}
            channels={options.general}
            busy={busy}
            disabled={saving || optionsLoading}
            onChange={(channelId) => onSave(voicePatch(game, { general: channelId }))}
          />

          {game.lobbies.map((lobby) => {
            const letter = lobbyLetter(lobby.lobby_index);
            return (
              <div key={lobby.lobby_index} className="flex flex-col gap-2">
                {multi ? <span className={EYEBROW_CLASS}>{t("lobby", { letter })}</span> : null}
                <div className="flex flex-wrap items-end gap-2">
                  {([1, 2] as const).map((team) => (
                    <VoiceSelect
                      key={team}
                      label={t("team", { n: team })}
                      // One lobby, one visible "Team 1" label; several, and the
                      // accessible name has to say which lobby it belongs to.
                      ariaLabel={
                        multi ? t("teamInLobby", { n: team, letter }) : t("team", { n: team })
                      }
                      value={
                        team === 1 ? lobby.team1_voice_channel_id : lobby.team2_voice_channel_id
                      }
                      channels={options.team}
                      busy={busy}
                      disabled={saving || optionsLoading}
                      onChange={(channelId) =>
                        onSave(voicePatch(game, { lobbyIndex: lobby.lobby_index, team, channelId }))
                      }
                    />
                  ))}
                  <Button
                    type="button"
                    className="h-9 shrink-0"
                    disabled={runDisabled}
                    onClick={() => onMove(lobby.lobby_index)}
                  >
                    {t("move")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 shrink-0"
                    disabled={runDisabled}
                    onClick={() => onReturn(lobby.lobby_index)}
                  >
                    {t("return")}
                  </Button>
                </div>
              </div>
            );
          })}

          {multi ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                className="h-9"
                disabled={runDisabled}
                onClick={() => onMove(null)}
              >
                {t("moveAll")}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-9"
                disabled={runDisabled}
                onClick={() => onReturn(null)}
              >
                {t("returnAll")}
              </Button>
            </div>
          ) : null}
        </>
      )}

      {report ? (
        <div className="flex flex-col gap-1">
          <p className="text-caption text-[color:var(--aqt-fg)]">
            {t("report.moved", { count: report.moved })}
          </p>
          {statuses.map((status) => (
            <p key={status} className={CAPTION_CLASS}>
              {t(`status.${status}`)}:{" "}
              {failures
                .filter((row) => row.status === status)
                .map((row) => row.name)
                .join(", ")}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
