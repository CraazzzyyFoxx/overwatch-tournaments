"use client";

import { forwardRef, useRef, useState, type ComponentPropsWithoutRef } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  MoreHorizontal,
  Send,
  Trash2,
  UserCog,
  UserPlus
} from "lucide-react";

import { MAX_LOBBIES, lobbyLetter } from "@/app/balancer/mix/pickup-chrome";
import { LobbyStage } from "@/app/balancer/mix/_components/LobbyStage";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { BanPresetSelect, useBanPresetName } from "@/components/pick-ban/BanPresetSelect";
import { MixFormationControl } from "@/components/mix/MixFormationControl";
import { Button } from "@/components/ui/button";
import { BackLink } from "@/components/site/BackLink";
import { Card } from "@/components/ui/card";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Eyebrow } from "@/components/ui/eyebrow";
import { NumberInput } from "@/components/ui/number-input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import {
  useMixPresetClocks,
  useMixPresetPickers,
  type MixPresetClocks,
  type MixPresetPickers
} from "@/hooks/useHeroBanPresets";
import { cn } from "@/lib/utils";
import type {
  CustomGame,
  CustomGameDiscordPost,
  MixSelfSignup,
  MixTeamFormation
} from "@/services/custom-game.service";

/** Where an open signup seats a player. `closed` is the other half of the switch. */
const SIGNUP_DESTINATIONS = ["pool", "benched"] as const;

/** The trigger's dot: shut, open straight into the pool, or open onto the bench. */
const SIGNUP_DOT: Record<MixSelfSignup, string> = {
  closed: "bg-[color:var(--aqt-fg-faint)]",
  pool: "bg-[color:var(--aqt-teal)]",
  benched: "bg-[color:var(--aqt-amber)]"
};

/** The live signup post: the NEWEST `mix.signup` row, the one a re-post just created. */
export function signupPostOf(game: CustomGame): CustomGameDiscordPost | null {
  return (game.discord_posts ?? []).findLast((row) => row.kind === "mix.signup") ?? null;
}

/**
 * The mode a signup post goes out in. Posting the card IS opening signup
 * (`signup_post` writes the mode server-side), so a closed mix opens into the
 * pool -- and every label that triggers this says so.
 */
export function postModeOf(mode: MixSelfSignup): "pool" | "benched" {
  return mode === "benched" ? "benched" : "pool";
}

/** A post still standing in the channel, or about to: re-posting replaces it. */
function isLive(post: CustomGameDiscordPost | null) {
  return post?.status === "pending" || post?.status === "posted";
}

type PickupMixHeaderProps = {
  /** Host or co-host, and not-terminal -- gates every write action in this header. */
  canWrite: boolean;
  game: CustomGame | undefined;
  gameLoading: boolean;
  onOpenPool: () => void;
  /** The mix's game has roles to order (`MixOwner.showsRoles`); `false` hides "Players edit their own roles". */
  showsRoles: boolean;
  /** Omitted -- the name is read-only. Resolve/reject so the editor knows whether to close. */
  onRename?: (name: string) => Promise<unknown>;
  onOpenAccess: () => void;
  /** Workspace admin (or superuser) -- gates the irreversible hard delete,
   * a stronger grant than the host-or-co-host `canWrite` above. */
  canDelete?: boolean;
  deleting?: boolean;
  onDeleteMix?: () => void;
  /** Omitted -- the self-service row is not offered at all. */
  onSetSelfService?: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
  savingSelfService?: boolean;
  /** Omitted -- the hero ban preset is shown read-only, as it is to every viewer. */
  onSetBanPreset?: (preset: string | null) => void;
  savingBanPreset?: boolean;
  /** Omitted -- Fearless is shown read-only (only while on), as it is to every viewer. */
  onSetFearless?: (fearless: boolean) => void;
  /** Omitted -- the hero room's clocks are shown read-only (only when set), as they are to every viewer. */
  onSetHeroClocks?: (clocks: HeroClocks) => void;
  /** Omitted -- who picks heroes is shown read-only (only when not the default), as it is to every viewer. */
  onSetHeroPickers?: (pickers: HeroPickers) => void;
  /** Omitted -- the formation is shown read-only, as it is to every viewer. */
  onSetDraftSettings?: (settings: { team_formation: MixTeamFormation; draft_pick_seconds: number }) => void;
  savingDraftSettings?: boolean;
  /** Omitted -- the Discord menu offers no signup post. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  postingSignup?: boolean;
  /** Omitted -- the Discord menu lists no posts (and so no way to delete one). */
  onDeleteDiscordPost?: (postId: number) => void;
  deletingDiscordPost?: boolean;
  settingLobbyCount?: boolean;
  /** Omitted -- the lobby-count choice is not offered. */
  onLobbyCountChange?: (lobbyCount: number) => void;
};

/**
 * The mix this screen is open on, in two fixed rows so it never wraps at
 * random: the way back, its name and id, and `⋯`; then what a host changes,
 * by how often they do it.
 *
 * Second row, one 32px subtle trigger each: the rules the next Start plays by
 * (bans, Fearless, formation -- set once an evening, so one popover), who may
 * sign up, what Discord shows, and Add players. None of them is solid: the
 * page's one solid button is the host's next step, under the matchup. A
 * viewer reads the rules as one line instead. Behind `⋯`: what is set once
 * per mix (how many lobbies, up to `MAX_LOBBIES`, and co-hosts) and the
 * irreversible delete.
 *
 * Which mix this is comes from the route, not from state this header owns --
 * switching to another one, or starting a new one, happens on the list at
 * `/balancer/mix`.
 */
export function PickupMixHeader({
  canWrite,
  game,
  gameLoading,
  onOpenPool,
  showsRoles,
  onOpenAccess,
  canDelete = false,
  deleting = false,
  onDeleteMix,
  onRename,
  onSetSelfService,
  savingSelfService = false,
  onSetBanPreset,
  savingBanPreset = false,
  onSetFearless,
  onSetHeroClocks,
  onSetHeroPickers,
  onSetDraftSettings,
  savingDraftSettings = false,
  onPostSignup,
  postingSignup = false,
  onDeleteDiscordPost,
  deletingDiscordPost = false,
  settingLobbyCount = false,
  onLobbyCountChange
}: Readonly<PickupMixHeaderProps>) {
  const tm = useTranslations("mixes");
  const tl = useTranslations("mixes.lobbies");
  const th = useTranslations("mixes.header");
  const tb = useTranslations("pickBan.mixBans");
  const banPresetName = useBanPresetName();
  const clocks = useMixPresetClocks(game?.discipline, game?.hero_ban_preset ?? null);
  const pickers = useMixPresetPickers(game?.discipline, game?.hero_ban_preset ?? null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dropLobbyOpen, setDropLobbyOpen] = useState(false);
  const lobbyCount = game?.lobby_count ?? 1;
  // What the slider shows while it is being dragged. The request only goes out
  // on release, so this follows the thumb and the mix's own count follows the
  // server. Reset during render when the mix's count changes under it (a
  // co-host's write landing, or this host's own confirm), React's own pattern.
  const [draftLobbyCount, setDraftLobbyCount] = useState(lobbyCount);
  const [syncedLobbyCount, setSyncedLobbyCount] = useState(lobbyCount);
  if (syncedLobbyCount !== lobbyCount) {
    setSyncedLobbyCount(lobbyCount);
    setDraftLobbyCount(lobbyCount);
  }
  // Dropping a lobby throws its balance away and clears the pins onto it, so it
  // is the direction that asks; opening one costs nothing. The names come from
  // the tab label, so the dialog calls them what the tabs do ("Lobby C").
  const droppedLobbies = Array.from(
    { length: Math.max(0, lobbyCount - draftLobbyCount) },
    (_, i) => tl("tab", { letter: lobbyLetter(draftLobbyCount + i) })
  ).join(", ");
  const offerDelete = canDelete && onDeleteMix != null;
  // One lobby: its stage is the mix's, said beside the name. Several: each lobby card says its own, so nothing here.
  const onlyLobby = lobbyCount === 1 ? game?.lobbies.find((row) => row.lobby_index === 0) : undefined;
  const offerRules =
    canWrite &&
    (onSetBanPreset != null ||
      onSetFearless != null ||
      onSetHeroClocks != null ||
      onSetHeroPickers != null ||
      onSetDraftSettings != null);
  // What the next Start plays by, said once: the host's Rules trigger and the viewers' line read the same words.
  const rulesSummary =
    game == null
      ? ""
      : [
          banPresetName(game.hero_ban_preset),
          game.team_formation === "draft" ? th("formationDraft") : th("formationBalance"),
          game.hero_fearless ? tb("fearless") : null,
          // A clock only when it is the host's own and the preset takes such a step at all.
          clocks.ban !== undefined && game.hero_ban_seconds != null
            ? tb("banClock", { seconds: game.hero_ban_seconds })
            : null,
          clocks.pick !== undefined && game.hero_pick_seconds != null
            ? tb("pickClock", { seconds: game.hero_pick_seconds })
            : null,
          // Who picks, only when it is not the default and the preset has player picks for it to change.
          pickers.turns && game.hero_free_order ? tb("freeOrder") : null,
          pickers.players && game.hero_captains_only ? tb("captainsOnly") : null
        ]
          .filter(Boolean)
          .join(" · ");

  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5">
      <div className="flex min-w-0 items-center gap-3">
        <BackLink href="/balancer/mix" className="shrink-0">
          {tm("title")}
        </BackLink>

        <Separator orientation="vertical" className="h-5" />

        {/* Wraps rather than squeezing: on a phone the id and the stage drop under the name, which keeps its width. */}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2.5 gap-y-1">
          {canWrite && game != null && onRename ? (
            <InlineEditText
              value={game.name}
              label={th("nameLabel")}
              onSave={onRename}
              className="min-w-0"
              textClassName="font-display text-title font-bold text-[color:var(--aqt-fg)]"
              inputClassName="h-8 max-w-sm"
            />
          ) : (
            <h1 className="min-w-0 truncate font-display text-title font-bold text-[color:var(--aqt-fg)]">
              {game?.name ?? (gameLoading ? "\u2026" : th("noMix"))}
            </h1>
          )}
          {game ? (
            <span className="aqt-tnum shrink-0 text-caption text-[color:var(--aqt-fg-faint)]">{`#${game.id}`}</span>
          ) : null}
          {onlyLobby?.state != null ? (
            <LobbyStage state={onlyLobby.state} startedAt={onlyLobby.live_started_at} />
          ) : null}
        </div>

        {canWrite || offerDelete ? (
          <DropdownMenu>
            <IconTooltip control label={th("more")} className="shrink-0">
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost" size="icon" disabled={game == null} aria-label={th("more")}>
                  <MoreHorizontal aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
            </IconTooltip>
            <DropdownMenuContent align="end" className="w-56">
              {canWrite && onLobbyCountChange ? (
                <>
                  <DropdownMenuLabel>{tl("countLabel")}</DropdownMenuLabel>
                  {/* The slider lives inside a menu that owns the arrow keys
                      and closes on a click: both stay with the control. */}
                  <div
                    className="flex items-center gap-3 px-2 pb-2 pt-1"
                    onKeyDown={(event) => event.stopPropagation()}
                    onPointerDown={(event) => event.stopPropagation()}
                    onPointerMove={(event) => event.stopPropagation()}
                  >
                    <Slider
                      aria-label={tl("countLabel")}
                      min={1}
                      max={MAX_LOBBIES}
                      step={1}
                      value={[draftLobbyCount]}
                      disabled={settingLobbyCount}
                      onValueChange={([next]) => setDraftLobbyCount(next)}
                      onValueCommit={([next]) => {
                        setDraftLobbyCount(next);
                        if (next === lobbyCount) return;
                        if (next < lobbyCount) setDropLobbyOpen(true);
                        else onLobbyCountChange(next);
                      }}
                    />
                    <span className="w-4 shrink-0 text-right text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                      {draftLobbyCount}
                    </span>
                  </div>
                  <DropdownMenuSeparator />
                </>
              ) : null}
              {canWrite ? (
                <DropdownMenuItem onSelect={onOpenAccess}>
                  <UserCog aria-hidden="true" />
                  {th("access")}
                </DropdownMenuItem>
              ) : null}
              {offerDelete ? (
                <>
                  {canWrite ? <DropdownMenuSeparator /> : null}
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={deleting}
                    onSelect={() => setDeleteOpen(true)}
                  >
                    <Trash2 aria-hidden="true" />
                    {th("delete")}
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      {canWrite ? (
        // One row of identical triggers -- label, value, chevron -- then the host's way to fill the lineup. Mounted
        // while the mix loads, Add players inert, so nothing shifts when it lands.
        <div className="flex flex-wrap items-center gap-2">
          {game == null ? null : offerRules ? (
            <RulesSettings
              game={game}
              summary={rulesSummary}
              savingBanPreset={savingBanPreset}
              onSetBanPreset={onSetBanPreset}
              onSetFearless={onSetFearless}
              clocks={clocks}
              onSetHeroClocks={onSetHeroClocks}
              pickers={pickers}
              onSetHeroPickers={onSetHeroPickers}
              savingDraftSettings={savingDraftSettings}
              onSetDraftSettings={onSetDraftSettings}
            />
          ) : (
            <p className="text-caption text-[color:var(--aqt-fg-muted)]">{rulesSummary}</p>
          )}

          {game != null && onSetSelfService ? (
            <SignupSettings
              game={game}
              showsRoles={showsRoles}
              saving={savingSelfService}
              onSetSelfService={onSetSelfService}
            />
          ) : null}

          {game != null && (onPostSignup || onDeleteDiscordPost) ? (
            <DiscordMenu
              game={game}
              posting={postingSignup}
              onPostSignup={onPostSignup}
              deleting={deletingDiscordPost}
              onDelete={onDeleteDiscordPost}
            />
          ) : null}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-auto shrink-0"
            disabled={game == null}
            onClick={onOpenPool}
          >
            <UserPlus aria-hidden="true" />
            {tm("start.addPlayers")}
          </Button>
        </div>
      ) : game == null ? null : (
        // Everyone reads what the next Start plays by; only a host changes it.
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{rulesSummary}</p>
      )}

      {canWrite && onLobbyCountChange ? (
        <ConfirmDialog
          open={dropLobbyOpen}
          onOpenChange={(open) => {
            setDropLobbyOpen(open);
            // Cancelled: the slider goes back to the count the mix still runs.
            if (!open) setDraftLobbyCount(lobbyCount);
          }}
          intent={{
            title: tl("dropTitle", { letters: droppedLobbies }),
            description: tl("dropDescription", { letters: droppedLobbies }),
            confirmLabel: tl("dropConfirm", { letters: droppedLobbies }),
            tone: "danger"
          }}
          pending={settingLobbyCount}
          onConfirm={() => {
            setDropLobbyOpen(false);
            onLobbyCountChange(draftLobbyCount);
          }}
        />
      ) : null}

      {offerDelete ? (
        <ConfirmDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          intent={{
            title: th("deleteTitle"),
            description: th("deleteDescription", { name: game?.name ?? th("thisMix") }),
            confirmLabel: th("deleteConfirm"),
            tone: "danger"
          }}
          pending={deleting}
          onConfirm={() => {
            setDeleteOpen(false);
            onDeleteMix?.();
          }}
        />
      ) : null}
    </Card>
  );
}

/**
 * One header trigger: a dim label, the value, a chevron -- the same 32px
 * subtle box for every setting, so the row reads as one control strip.
 */
const SettingTrigger = forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<typeof Button> & { label: string }>(
  function SettingTrigger({ label, children, className, ...props }, ref) {
    return (
      <Button ref={ref} type="button" variant="outline" size="sm" className={cn("max-w-full shrink-0", className)} {...props}>
        <span className="shrink-0 text-[color:var(--aqt-fg-dim)]">{label}</span>
        {children}
        <ChevronDown className="text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
      </Button>
    );
  }
);

/** The hero room's clocks a header write sends; an omitted one stays as it is, null hands it back to the preset. */
type HeroClocks = { hero_ban_seconds?: number | null; hero_pick_seconds?: number | null };

/** Who picks the room's heroes, as a header write sends it; an omitted one stays as it is. */
type HeroPickers = { hero_free_order?: boolean; hero_captains_only?: boolean };

/**
 * What the next Start plays by -- hero bans, Fearless, the room's clocks, who picks, how teams form -- set
 * once an evening, so one trigger that reads the whole rule set instead of
 * three controls in the row. Every field writes on change; a clock when it is left.
 */
function RulesSettings({
  game,
  summary,
  savingBanPreset,
  onSetBanPreset,
  onSetFearless,
  clocks,
  onSetHeroClocks,
  pickers,
  onSetHeroPickers,
  savingDraftSettings,
  onSetDraftSettings
}: Readonly<{
  game: CustomGame;
  summary: string;
  savingBanPreset: boolean;
  onSetBanPreset?: (preset: string | null) => void;
  onSetFearless?: (fearless: boolean) => void;
  /** The preset's own clocks: a field only for a step the preset takes, its seconds the empty field's hint. */
  clocks: MixPresetClocks;
  onSetHeroClocks?: (clocks: HeroClocks) => void;
  /** Whether the preset has player picks at all, and turn-by-turn ones: a choice only for what it would change. */
  pickers: MixPresetPickers;
  onSetHeroPickers?: (pickers: HeroPickers) => void;
  savingDraftSettings: boolean;
  onSetDraftSettings?: (settings: { team_formation: MixTeamFormation; draft_pick_seconds: number }) => void;
}>) {
  const th = useTranslations("mixes.header");
  const tb = useTranslations("pickBan.mixBans");
  const banPresetName = useBanPresetName();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <SettingTrigger label={th("rules")} aria-label={th("rulesTrigger", { rules: summary })} title={summary}>
          {/* A long preset name ("Three blind bans, one per role") truncates rather than pushing Add players
              onto a line of its own; the full rules are in the title and the accessible name. */}
          <span className="min-w-0 max-w-56 truncate">{summary}</span>
        </SettingTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[22rem] space-y-3 p-3">
        <div className="space-y-1.5">
          <Eyebrow as="label" htmlFor="mix-header-bans">
            {tb("label")}
          </Eyebrow>
          {onSetBanPreset ? (
            <BanPresetSelect
              id="mix-header-bans"
              discipline={game.discipline}
              label={tb("label")}
              value={game.hero_ban_preset}
              disabled={savingBanPreset}
              onChange={onSetBanPreset}
            />
          ) : (
            <p id="mix-header-bans" className="text-caption text-[color:var(--aqt-fg)]">
              {banPresetName(game.hero_ban_preset)}
            </p>
          )}
        </div>
        {onSetFearless ? (
          <label className="flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
            <Switch
              size="sm"
              checked={game.hero_fearless}
              disabled={savingBanPreset}
              aria-label={tb("fearless")}
              onCheckedChange={onSetFearless}
            />
            {tb("fearless")}
          </label>
        ) : null}
        {onSetHeroClocks && (clocks.ban !== undefined || clocks.pick !== undefined) ? (
          <div className="space-y-1.5">
            {clocks.ban !== undefined ? (
              <HeroClockField
                id="mix-header-ban-seconds"
                label={tb("banSeconds")}
                value={game.hero_ban_seconds}
                presetSeconds={clocks.ban}
                disabled={savingBanPreset}
                onCommit={(seconds) => onSetHeroClocks({ hero_ban_seconds: seconds })}
              />
            ) : null}
            {clocks.pick !== undefined ? (
              <HeroClockField
                id="mix-header-pick-seconds"
                label={tb("pickSeconds")}
                value={game.hero_pick_seconds}
                presetSeconds={clocks.pick}
                disabled={savingBanPreset}
                onCommit={(seconds) => onSetHeroClocks({ hero_pick_seconds: seconds })}
              />
            ) : null}
            <p className="text-caption text-[color:var(--aqt-fg-faint)]">{tb("clocksHint")}</p>
          </div>
        ) : null}
        {onSetHeroPickers && pickers.turns ? (
          <PickerChoice
            label={tb("pickOrder")}
            value={game.hero_free_order}
            off={tb("pickOrderLineup")}
            on={tb("pickOrderFree")}
            disabled={savingBanPreset}
            onChange={(free) => onSetHeroPickers({ hero_free_order: free })}
          />
        ) : null}
        {onSetHeroPickers && pickers.players ? (
          <PickerChoice
            label={tb("pickers")}
            value={game.hero_captains_only}
            off={tb("pickersPlayers")}
            on={tb("pickersCaptains")}
            disabled={savingBanPreset}
            onChange={(captainsOnly) => onSetHeroPickers({ hero_captains_only: captainsOnly })}
          />
        ) : null}
        <div className="space-y-1.5 border-t border-[color:var(--aqt-border)] pt-3">
          <Eyebrow as="label" htmlFor="mix-header-formation">
            {th("formation")}
          </Eyebrow>
          {onSetDraftSettings ? (
            <MixFormationControl
              commitOnBlur
              idPrefix="mix-header"
              value={{ team_formation: game.team_formation, draft_pick_seconds: game.draft_pick_seconds }}
              disabled={savingDraftSettings}
              onChange={onSetDraftSettings}
            />
          ) : (
            <p id="mix-header-formation" className="text-caption text-[color:var(--aqt-fg)]">
              {game.team_formation === "draft" ? th("formationDraft") : th("formationBalance")}
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/**
 * One of the hero room's clocks, in seconds (10..600). Empty is the preset's own, whose seconds the empty field
 * shows; one write when the field is left, not "4" on the way to "45".
 */
function HeroClockField({
  id,
  label,
  value,
  presetSeconds,
  disabled,
  onCommit
}: Readonly<{
  id: string;
  label: string;
  value: number | null;
  presetSeconds: number | null;
  disabled: boolean;
  onCommit: (seconds: number | null) => void;
}>) {
  // NumberInput reports the clamped value (or null when emptied) right before its onBlur, so this is never stale there.
  const typed = useRef<number | null>(value);
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
      <NumberInput
        id={id}
        integer
        min={10}
        max={600}
        placeholder={presetSeconds != null ? String(presetSeconds) : undefined}
        disabled={disabled}
        value={value}
        onValueChange={(next) => {
          typed.current = next;
        }}
        onBlur={() => {
          if (typed.current !== value) onCommit(typed.current);
        }}
        size="sm"
        className="w-16"
      />
      {label}
    </label>
  );
}

/** One of who-picks' two-way choices (lineup or free order; players or captains only), `on` the non-default one. */
function PickerChoice({
  label,
  value,
  off,
  on,
  disabled,
  onChange
}: Readonly<{
  label: string;
  value: boolean;
  off: string;
  on: string;
  disabled: boolean;
  onChange: (value: boolean) => void;
}>) {
  return (
    <div className="space-y-1.5">
      <Eyebrow>{label}</Eyebrow>
      <ToggleGroup
        variant="pill"
        aria-label={label}
        value={value ? "on" : "off"}
        onValueChange={(next) => {
          // A click on the pressed item deselects it in a single group: that is no change.
          if (next === "" || (next === "on") === value) return;
          onChange(next === "on");
        }}
        className="flex w-full"
      >
        <ToggleGroupItem value="off" disabled={disabled} className="flex-1 whitespace-nowrap px-2">
          {off}
        </ToggleGroupItem>
        <ToggleGroupItem value="on" disabled={disabled} className="flex-1 whitespace-nowrap px-2">
          {on}
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
  );
}

/**
 * Who may sign up, and nothing else: Discord lives in its own menu.
 *
 * The column has three values but the host thinks in two steps -- is signup
 * open at all, and if so, where does a new player land -- so the popover asks
 * exactly that, and the trigger reads as a state ("Open · to the pool"), not
 * as a destination that looked like a button. Every control writes on change:
 * there is nothing to save or cancel.
 */
function SignupSettings({
  game,
  showsRoles,
  saving,
  onSetSelfService
}: Readonly<{
  game: CustomGame;
  showsRoles: boolean;
  saving: boolean;
  onSetSelfService: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
}>) {
  const t = useTranslations("mixes.self");
  const mode = game.self_signup;
  const open = mode !== "closed";
  const stateLabel = t(`signupState.${mode}`);
  // The pool is where an open signup lands by default, so the trigger says only "Open"; the bench, the exception,
  // stays spelled out. The accessible name keeps the full state either way.
  const shortLabel = mode === "pool" ? t("signupOpen") : stateLabel;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <SettingTrigger label={t("signupLabel")} aria-label={t("signupTrigger", { mode: stateLabel })}>
          <span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", SIGNUP_DOT[mode])} />
          {shortLabel}
        </SettingTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[22rem] space-y-3 p-3">
        <ToggleGroup
          variant="pill"
          aria-label={t("signupLabel")}
          value={open ? "open" : "closed"}
          onValueChange={(value) => {
            if ((value === "open") === open) return;
            onSetSelfService({ self_signup: value === "open" ? "pool" : "closed" });
          }}
          className="flex w-full"
        >
          <ToggleGroupItem value="closed" disabled={saving} className="flex-1 whitespace-nowrap px-2">
            {t("signupState.closed")}
          </ToggleGroupItem>
          <ToggleGroupItem value="open" disabled={saving} className="flex-1 whitespace-nowrap px-2">
            {t("signupOpen")}
          </ToggleGroupItem>
        </ToggleGroup>

        {open ? (
          <div className="space-y-2">
            <Eyebrow>{t("signupWhere")}</Eyebrow>
            <ToggleGroup
              variant="pill"
              aria-label={t("signupWhere")}
              value={mode}
              onValueChange={(value) => onSetSelfService({ self_signup: value as MixSelfSignup })}
              className="flex w-full"
            >
              {SIGNUP_DESTINATIONS.map((value) => (
                <ToggleGroupItem key={value} value={value} disabled={saving} className="flex-1 whitespace-nowrap px-2">
                  {t(`signup.${value}`)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}
        <p className="text-label text-[color:var(--aqt-fg-dim)]">{t(`signupHint.${mode}`)}</p>

        {showsRoles ? (
          <div className="flex items-center gap-2 border-t border-[color:var(--aqt-border)] pt-3">
            <Switch
              size="sm"
              checked={game.self_role_edit}
              disabled={saving}
              aria-label={t("roleEdit")}
              onCheckedChange={(checked) => onSetSelfService({ self_role_edit: checked })}
            />
            <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("roleEdit")}</span>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

const POST_STATUS_TONE: Record<CustomGameDiscordPost["status"], string> = {
  pending: "text-[color:var(--aqt-fg-dim)]",
  deleting: "text-[color:var(--aqt-fg-dim)]",
  posted: "text-[color:var(--aqt-teal)]",
  failed: "text-[color:var(--aqt-rose)]",
  lost: "text-[color:var(--aqt-rose)]"
};

/**
 * Everything this mix has in Discord, behind one trigger that shows where the
 * signup post stands -- the bot answers asynchronously, so the press alone
 * tells the host nothing.
 *
 * Inside: what the signup post is, its status, and one button whose label is
 * what it will actually do (post, re-post, or open signup and post), then
 * every post the mix made with a link and a delete. Delete asks first -- the
 * message disappears for everyone -- and its confirm lives outside the
 * popover, which closes as the dialog takes focus.
 *
 * Without a mix channel the menu still opens and says why the post is not
 * offered: a missing button reads as a bug, a stated reason as an answer.
 */
function DiscordMenu({
  game,
  posting,
  onPostSignup,
  deleting,
  onDelete
}: Readonly<{
  game: CustomGame;
  posting: boolean;
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  deleting: boolean;
  onDelete?: (postId: number) => void;
}>) {
  const t = useTranslations("mixes.self");
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<CustomGameDiscordPost | null>(null);
  const posts = game.discord_posts ?? [];
  const signupPost = signupPostOf(game);
  const status = signupPost?.status ?? null;
  const failed = status === "failed" || status === "lost";
  const statusLabel = t(status ? `post.${status}` : "post.none");
  const hasChannel = game.settings.workspace_discord_channel_id != null;
  const closed = game.self_signup === "closed";
  const postLabel = closed
    ? t("discord.openAndPost")
    : isLive(signupPost)
      ? t("discord.repost")
      : t("discord.post");
  const postHint = closed
    ? t("discord.openHint")
    : isLive(signupPost)
      ? t("discord.repostHint")
      : null;

  // What a post is, from its slot: the signup card, or one lineup card -- the
  // lobby letter only when the mix runs more than one lobby, since with one it
  // says nothing. The slot is `lineup:<lobby_index>:<game number>`.
  const labelOf = (post: CustomGameDiscordPost) => {
    if (post.slot === "signup") return t("posts.signup");
    const [prefix, lobby, match] = post.slot.split(":");
    if (prefix !== "lineup") return post.slot;
    return game.lobby_count > 1
      ? t("posts.lineupLobby", { lobby: lobbyLetter(Number(lobby)), match })
      : t("posts.lineup", { match });
  };

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <SettingTrigger
            label={t("discord.label")}
            aria-label={t("discord.trigger", { status: statusLabel })}
            className={cn(failed && "border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)]")}
          >
            {status === "pending" || status === "deleting" ? <Spinner /> : null}
            {status === "posted" ? (
              <CheckCircle2 className="text-[color:var(--aqt-teal)]" aria-hidden="true" />
            ) : null}
            {failed ? <AlertTriangle className="text-[color:var(--aqt-rose)]" aria-hidden="true" /> : null}
            <span className={status ? POST_STATUS_TONE[status] : "text-[color:var(--aqt-fg-dim)]"}>
              {statusLabel}
            </span>
          </SettingTrigger>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[22rem] space-y-3 p-3">
          {onPostSignup ? (
            <div className="space-y-2">
              <Eyebrow>{t("posts.signup")}</Eyebrow>
              <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("discord.hint")}</p>
              <SignupPostStatus post={signupPost} />
              {hasChannel ? (
                <>
                  <Button
                    type="button"
                    // Re-posting a card that is up is a repair, not the next step.
                    variant={!closed && isLive(signupPost) ? "outline" : "default"}
                    className="w-full"
                    disabled={posting}
                    onClick={() => onPostSignup(postModeOf(game.self_signup))}
                  >
                    {posting ? <Spinner /> : <Send aria-hidden="true" />}
                    {postLabel}
                  </Button>
                  {postHint ? (
                    <p className="text-label text-[color:var(--aqt-fg-muted)]">{postHint}</p>
                  ) : null}
                </>
              ) : (
                <p className="text-caption text-[color:var(--aqt-amber)]">{t("noChannel")}</p>
              )}
            </div>
          ) : null}

          {onDelete && posts.length > 0 ? (
            <div
              className={cn(
                "space-y-1",
                onPostSignup && "border-t border-[color:var(--aqt-border)] pt-3"
              )}
            >
              <Eyebrow>{t("discord.allPosts")}</Eyebrow>
              <ul
                aria-label={t("discord.allPosts")}
                className="max-h-60 space-y-0.5 overflow-y-auto"
              >
                {posts.map((post) => {
                  const label = labelOf(post);
                  return (
                    <li key={post.id} className="flex items-center gap-2 rounded-md py-1">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-caption text-[color:var(--aqt-fg)]">
                          {label}
                        </div>
                        <div
                          className={cn("truncate text-label", POST_STATUS_TONE[post.status])}
                          title={post.status === "failed" ? (post.error ?? undefined) : undefined}
                        >
                          {t(`post.${post.status}`)}
                        </div>
                      </div>
                      {post.url ? (
                        <a
                          href={post.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex shrink-0 items-center gap-1 text-caption text-[color:var(--aqt-teal)] hover:underline"
                        >
                          {t("posts.open")}
                          <ExternalLink className="size-3" aria-hidden="true" />
                        </a>
                      ) : null}
                      <IconTooltip
                        control
                        label={t("posts.delete", { label })}
                        className="shrink-0"
                      >
                        <Button
                          type="button"
                          variant="ghost-destructive"
                          size="icon-sm"
                          disabled={post.status === "deleting"}
                          aria-label={t("posts.delete", { label })}
                          onClick={() => {
                            setOpen(false);
                            setConfirming(post);
                          }}
                        >
                          <Trash2 aria-hidden="true" />
                        </Button>
                      </IconTooltip>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </PopoverContent>
      </Popover>
      {onDelete ? (
        <ConfirmDialog
          open={confirming != null}
          onOpenChange={(next) => {
            if (!next) setConfirming(null);
          }}
          intent={{
            title: t("posts.deleteTitle"),
            description: t("posts.deleteDescription", {
              label: confirming ? labelOf(confirming) : ""
            }),
            confirmLabel: t("posts.deleteConfirm"),
            tone: "danger"
          }}
          pending={deleting}
          onConfirm={() => {
            if (confirming) onDelete(confirming.id);
            setConfirming(null);
          }}
        />
      ) : null}
    </>
  );
}

/**
 * Where the live signup post stands, above the button that (re)posts it:
 * `pending` until the bot writes the row, then a link to the message, or the
 * reason Discord refused -- almost always the bot's permissions in the mix
 * channel, which the host fixes and then simply posts again. `lost` is the
 * command that expired in the queue before the bot ever saw it.
 *
 * The `role="status"` region is mounted with the popover and stays mounted
 * while there is nothing to say: screen readers only announce changes to a
 * live region that already existed.
 */
function SignupPostStatus({ post }: Readonly<{ post: CustomGameDiscordPost | null }>) {
  const t = useTranslations("mixes.self");
  const status = post?.status ?? null;
  const error = post?.error?.trim().replace(/\.$/, "");
  const failedReason = error ? `${error}. ${t("post.failedHint")}` : t("post.failedHint");
  const posted = (
    <>
      <CheckCircle2 className="size-3.5" aria-hidden="true" />
      {t("post.posted")}
    </>
  );

  return (
    <div role="status" className="text-caption">
      {status === "pending" || status === "deleting" ? (
        <span className="flex items-center gap-1.5 text-[color:var(--aqt-fg-dim)]">
          <Spinner className="size-3.5" />
          {t(`post.${status}`)}
        </span>
      ) : null}
      {status === "posted" && post?.url ? (
        <a
          href={post.url}
          target="_blank"
          rel="noreferrer"
          className="flex w-fit items-center gap-1.5 text-[color:var(--aqt-teal)] hover:underline"
        >
          {posted}
          <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      ) : null}
      {status === "posted" && !post?.url ? (
        <span className="flex items-center gap-1.5 text-[color:var(--aqt-teal)]">{posted}</span>
      ) : null}
      {status === "failed" || status === "lost" ? (
        <div className="space-y-0.5">
          <span className="flex items-center gap-1.5 text-[color:var(--aqt-rose)]">
            <AlertTriangle className="size-3.5" aria-hidden="true" />
            {t(`post.${status}`)}
          </span>
          <p className="text-label text-[color:var(--aqt-fg-muted)]">
            {status === "failed" ? failedReason : t("post.lostHint")}
          </p>
        </div>
      ) : null}
    </div>
  );
}
