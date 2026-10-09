"use client";

import { useState, type ReactNode } from "react";
import { Check, Pencil, Split, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  lobbyLetter,
  teamAccent,
} from "@/app/balancer/mix/pickup-chrome";
import { teamNamesByIndex } from "@/app/balancer/mix/pickup-lineup";
import { busyVoices, voiceBlocker, voicePatch, type BusyVoice } from "@/app/balancer/mix/pickup-voice";
import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
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
import type { DiscordVoicePermission } from "@/types/discord.types";

/** Radix refuses an empty item value, and a channel id is always digits. */
const NONE = "none";

/** A lobby row's own move/return: quiet chrome, so the voices stay the row's subject. */
const ROW_ACTION_CLASS =
  "border border-[color:var(--aqt-border)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]";

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
  /** Which lobby `report` answers for; `null` when it was every lobby at once. */
  reportLobby?: number | null;
  onSave: (patch: MixVoicePatch) => void;
  onMove: (lobbyIndex: number | null) => void;
  onReturn: (lobbyIndex: number | null) => void;
};

/** The voice action waiting on the host's "yes": which way, and one lobby or every one (`null`). */
type VoiceAsk = { kind: "move" | "return"; lobbyIndex: number | null };

/** The team a voice belongs to: its colour bar and its name, as the teams panel shows them. */
function TeamTag({ index, name }: Readonly<{ index: number; name: string }>) {
  return (
    <span className="flex min-w-0 max-w-[55%] shrink-0 items-center gap-1.5 text-[color:var(--aqt-fg-dim)]">
      <span aria-hidden className={cn("h-3.5 w-0.5 shrink-0 rounded-full", teamAccent(index).bar)} />
      <span className="truncate">{name}</span>
    </span>
  );
}

type VoiceSelectProps = {
  ariaLabel: string;
  /** Shown inside the trigger before the voice: whose voice this is. */
  prefix?: ReactNode;
  value: string | null;
  channels: MixVoiceChannel[];
  busy: Map<string, BusyVoice>;
  disabled: boolean;
  onChange: (channelId: string | null) => void;
};

/**
 * One voice pick. Everything a host needs to judge a voice is in its list:
 * whether another mix is already in it, and whether the bot can use it at all.
 */
function VoiceSelect({
  ariaLabel,
  prefix,
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
    <Select
      value={value ?? NONE}
      disabled={disabled}
      onValueChange={(next) => onChange(next === NONE ? null : next)}
    >
      <SelectTrigger aria-label={ariaLabel} className="h-9 min-w-0">
        <span className="flex min-w-0 flex-1 items-center gap-2">
          {prefix}
          <span className="min-w-0 truncate">
            <SelectValue />
          </span>
        </span>
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
  );
}

/** A settled pick, read-only: the same cell as the select, minus the chrome. */
function VoiceValue({
  prefix,
  value,
  channels,
  busy,
}: Readonly<{ prefix?: ReactNode; value: string | null; channels: MixVoiceChannel[]; busy: Map<string, BusyVoice> }>) {
  const t = useTranslations("mixes.voice");
  const channel = channels.find((candidate) => candidate.id === value);
  const taken = value == null ? undefined : busy.get(value);
  return (
    <div className="flex h-9 min-w-0 items-center gap-2 rounded-md bg-white/[0.025] px-3 text-sm">
      {prefix}
      <span className="min-w-0 truncate text-[color:var(--aqt-fg)]">
        {channel?.name ?? t(value == null ? "none" : "outsideCategory")}
      </span>
      {taken ? (
        <span className={cn(CAPTION_CLASS, "truncate")}>
          {t("busy", { mix: taken.gameName, letter: lobbyLetter(taken.lobbyIndex) })}
        </span>
      ) : null}
    </div>
  );
}

function MissingAlert({ permissions }: Readonly<{ permissions: DiscordVoicePermission[] }>) {
  const t = useTranslations("mixes.voice");
  return (
    <Alert variant="destructive" className="py-2">
      <AlertDescription>
        {t("missing", { permissions: permissions.map((name) => t(`permission.${name}`)).join(", ") })}
      </AlertDescription>
    </Alert>
  );
}

/** How many moved and, per status, exactly who did not. */
function VoiceReportLines({ report }: Readonly<{ report: MixVoiceReport }>) {
  const t = useTranslations("mixes.voice");
  // A non-moved result is the only one worth naming: who moved is the count.
  const failures = report.results.filter((row) => row.status !== "moved");
  const statuses = [...new Set(failures.map((row) => row.status))] as Exclude<MixVoiceStatus, "moved">[];
  return (
    <div className="flex flex-col gap-1" role="status">
      <p className="text-caption text-[color:var(--aqt-fg)]">{t("report.moved", { count: report.moved })}</p>
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
 * click, with the missing permission named, on the lobby it concerns.
 *
 * Picks are set up once and moves happen every match, so once every voice is
 * picked the selects fold into read-only cells and only the actions stay live.
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
  reportLobby,
  onSave,
  onMove,
  onReturn,
}: Readonly<PickupVoicePanelProps>) {
  const t = useTranslations("mixes.voice");
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState(false);
  // Kept after the dialog closes so its text does not flip during the close animation.
  const [ask, setAsk] = useState<VoiceAsk>({ kind: "move", lobbyIndex: null });
  const confirm = (next: VoiceAsk) => {
    setAsk(next);
    setAsking(true);
  };

  const general = game.general_voice_channel_id;
  const busy = busyVoices(games, game.id);
  const multi = game.lobby_count > 1;
  const running = moving || returning;
  const configured =
    general != null &&
    game.lobbies.every((lobby) => lobby.team1_voice_channel_id != null && lobby.team2_voice_channel_id != null);
  const open = editing || !configured;
  // The category's gaps and the general voice's touch every lobby; a team
  // voice's own gaps are said on its lobby's row.
  const shared = voiceBlocker(options, [general]);
  const rows = game.lobbies.map((lobby) => {
    const teams = [lobby.team1_voice_channel_id, lobby.team2_voice_channel_id];
    const moveBlocker = voiceBlocker(options, teams);
    const picked = teams.every((id) => id != null);
    return {
      lobby,
      letter: lobbyLetter(lobby.lobby_index),
      names: teamNamesByIndex(game.settings, lobby.lobby_index),
      missing: moveBlocker.filter((permission) => !shared.includes(permission)),
      // Half a lobby split is not a split: the other team stays in the general voice.
      canMove: picked && moveBlocker.length === 0,
      canReturn: general != null && picked && voiceBlocker(options, [general, ...teams]).length === 0,
      hint: !picked ? t("pickTeams") : general == null ? t("pickGeneral") : null,
    };
  });
  // A single lobby has no "every lobby" row, so its report is always its own.
  const reportAt = report == null ? undefined : multi ? (reportLobby ?? null) : 0;

  return (
    <section className={cn(PANEL_CLASS, "flex flex-col gap-3 px-4 py-3.5")}>
      <div className="flex min-h-8 items-center justify-between gap-3">
        <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>
        {options?.category_id != null && configured ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1.5 text-[color:var(--aqt-fg-muted)]"
            onClick={() => setEditing(!editing)}
          >
            {editing ? <Check className="size-3.5" /> : <Pencil className="size-3.5" />}
            {editing ? t("done") : t("edit")}
          </Button>
        ) : null}
      </div>

      {options == null ? null : options.category_id == null ? (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("notConfigured")}</p>
      ) : (
        <>
          {options.error ? <p className="text-caption text-amber-200">{t("unreachable")}</p> : null}
          {shared.length > 0 ? <MissingAlert permissions={shared} /> : null}

          <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
            <span className="shrink-0 text-sm text-[color:var(--aqt-fg-muted)]">{t("general")}</span>
            <div className="min-w-0 sm:w-72">
              {open ? (
                <VoiceSelect
                  ariaLabel={t("general")}
                  value={general}
                  channels={options.general}
                  busy={busy}
                  disabled={saving || optionsLoading}
                  onChange={(channelId) => onSave(voicePatch(game, { general: channelId }))}
                />
              ) : (
                <VoiceValue value={general} channels={options.general} busy={busy} />
              )}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            {rows.map(({ lobby, letter, names, missing, canMove, canReturn, hint }) => (
              <div
                key={lobby.lobby_index}
                role="group"
                aria-label={multi ? t("lobby", { letter }) : undefined}
                className="flex flex-col gap-2"
              >
                <div
                  className={cn(
                    "grid grid-cols-1 items-center gap-2",
                    multi
                      ? "md:grid-cols-[1.25rem_minmax(0,1fr)_minmax(0,1fr)_auto]"
                      : "md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]",
                  )}
                >
                  {multi ? (
                    <span aria-hidden className="font-display text-sm font-bold text-[color:var(--aqt-fg-muted)]">
                      {letter}
                    </span>
                  ) : null}
                  {([1, 2] as const).map((team) => {
                    const value = team === 1 ? lobby.team1_voice_channel_id : lobby.team2_voice_channel_id;
                    const prefix = <TeamTag index={team - 1} name={names[team - 1] ?? t("team", { n: team })} />;
                    return open ? (
                      <VoiceSelect
                        key={team}
                        prefix={prefix}
                        // One lobby, one "Team 1"; several, and the accessible
                        // name has to say which lobby it belongs to.
                        ariaLabel={multi ? t("teamInLobby", { n: team, letter }) : t("team", { n: team })}
                        value={value}
                        channels={options.team}
                        busy={busy}
                        disabled={saving || optionsLoading}
                        onChange={(channelId) =>
                          onSave(voicePatch(game, { lobbyIndex: lobby.lobby_index, team, channelId }))
                        }
                      />
                    ) : (
                      <VoiceValue key={team} prefix={prefix} value={value} channels={options.team} busy={busy} />
                    );
                  })}
                  <div className="flex gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      // With several lobbies the footer's "every lobby" is the main action.
                      variant={multi ? "ghost" : "default"}
                      className={cn("h-8 shrink-0 gap-1.5 px-2.5", multi && ROW_ACTION_CLASS)}
                      disabled={running || !canMove}
                      onClick={() => confirm({ kind: "move", lobbyIndex: lobby.lobby_index })}
                    >
                      <Split className="size-3.5" />
                      {t("move")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className={cn("h-8 shrink-0 gap-1.5 px-2.5", ROW_ACTION_CLASS)}
                      disabled={running || !canReturn}
                      onClick={() => confirm({ kind: "return", lobbyIndex: lobby.lobby_index })}
                    >
                      <Undo2 className="size-3.5" />
                      {t("return")}
                    </Button>
                  </div>
                </div>
                {missing.length > 0 ? <MissingAlert permissions={missing} /> : null}
                {hint ? <p className={CAPTION_CLASS}>{hint}</p> : null}
                {report != null && reportAt === lobby.lobby_index ? <VoiceReportLines report={report} /> : null}
              </div>
            ))}
          </div>

          {multi ? (
            <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border-2)] pt-3">
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9"
                  disabled={running || !rows.every((row) => row.canReturn)}
                  onClick={() => confirm({ kind: "return", lobbyIndex: null })}
                >
                  {t("returnAll")}
                </Button>
                <Button
                  type="button"
                  className="h-9"
                  disabled={running || !rows.every((row) => row.canMove)}
                  onClick={() => confirm({ kind: "move", lobbyIndex: null })}
                >
                  {t("moveAll")}
                </Button>
              </div>
              {report != null && reportAt === null ? <VoiceReportLines report={report} /> : null}
            </div>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        intent={{
          title: t(ask.kind === "move" ? "confirm.moveTitle" : "confirm.returnTitle"),
          description: t("confirm.where", {
            mix: game.name,
            lobby:
              ask.lobbyIndex == null
                ? t("confirm.allLobbies")
                : t("lobby", { letter: lobbyLetter(ask.lobbyIndex) }),
          }),
          confirmLabel: t(ask.kind),
          tone: "warning",
        }}
        onConfirm={() => {
          setAsking(false);
          (ask.kind === "move" ? onMove : onReturn)(ask.lobbyIndex);
        }}
      />
    </section>
  );
}
