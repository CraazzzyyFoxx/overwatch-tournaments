"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  MoreHorizontal,
  Send,
  Shuffle,
  Trash2,
  UserCog,
  UserPlus
} from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { segmentedFrame, toggleVariants } from "@/components/ui/toggle";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type {
  CustomGame,
  CustomGameDiscordPost,
  MixSelfSignup
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
  onOpenAccess: () => void;
  /** Workspace admin (or superuser) -- gates the irreversible hard delete,
   * a stronger grant than the host-or-co-host `canWrite` above. */
  canDelete?: boolean;
  deleting?: boolean;
  onDeleteMix?: () => void;
  /** Omitted -- the self-service row is not offered at all. */
  onSetSelfService?: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
  savingSelfService?: boolean;
  /** Omitted -- the Discord menu offers no signup post. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  postingSignup?: boolean;
  /** Omitted -- the Discord menu lists no posts (and so no way to delete one). */
  onDeleteDiscordPost?: (postId: number) => void;
  deletingDiscordPost?: boolean;
  settingLobbyCount?: boolean;
  /** Omitted -- the lobby-count choice is not offered. */
  onLobbyCountChange?: (lobbyCount: 1 | 2) => void;
  shufflingAll?: boolean;
  /** Omitted -- no shared reshuffle, matching a page that offers none. */
  onShuffleAll?: () => void;
};

/**
 * The mix this screen is open on: the way back to the list, its name and id,
 * and what a host does with it, by how often they do it.
 *
 * Visible: who may sign up, what Discord shows, the shared reshuffle while two
 * lobbies run, and Add players -- the one solid action. Behind `⋯`: what is set
 * once per mix (lobby count, co-hosts) and the irreversible delete. A flat row
 * of nine equal outline buttons truncated the mix's own name to five letters.
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
  onOpenAccess,
  canDelete = false,
  deleting = false,
  onDeleteMix,
  onSetSelfService,
  savingSelfService = false,
  onPostSignup,
  postingSignup = false,
  onDeleteDiscordPost,
  deletingDiscordPost = false,
  settingLobbyCount = false,
  onLobbyCountChange,
  shufflingAll = false,
  onShuffleAll
}: Readonly<PickupMixHeaderProps>) {
  const tl = useTranslations("mixes.lobbies");
  const th = useTranslations("mixes.header");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dropLobbyOpen, setDropLobbyOpen] = useState(false);
  const [shuffleOpen, setShuffleOpen] = useState(false);
  const lobbyCount = game?.lobby_count ?? 1;
  // A lineup that was balanced and never played into the log: a shared
  // reshuffle would replace it with nothing left to record it from.
  const unrecorded = (game?.lobbies ?? []).some((lobby) => lobby.lineup_recorded === false);
  const offerDelete = canDelete && onDeleteMix != null;

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

      <div className="flex min-w-[12rem] flex-1 items-center gap-2.5">
        <h1 className="min-w-0 truncate font-display text-xl font-bold tracking-[-0.01em] text-[color:var(--aqt-fg)]">
          {game?.name ?? (gameLoading ? "\u2026" : "No mix yet")}
        </h1>
        {game ? (
          <span className="shrink-0 text-caption font-semibold text-[color:var(--aqt-fg-dim)]">
            {`#${game.id}`}
          </span>
        ) : null}
      </div>

      {/* One block: when the row runs out of width it wraps as a whole, under
          the name, instead of orphaning the last button on a line of its own. */}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
        {canWrite && game != null && onSetSelfService ? (
          <SignupSettings
            game={game}
            saving={savingSelfService}
            onSetSelfService={onSetSelfService}
          />
        ) : null}

        {canWrite && game != null && (onPostSignup || onDeleteDiscordPost) ? (
          <DiscordMenu
            game={game}
            posting={postingSignup}
            onPostSignup={onPostSignup}
            deleting={deletingDiscordPost}
            onDelete={onDeleteDiscordPost}
          />
        ) : null}

        {canWrite && onShuffleAll && lobbyCount === 2 ? (
          <>
            <Button
              type="button"
              variant="outline"
              className="h-9 shrink-0"
              disabled={game == null || shufflingAll}
              onClick={() => (unrecorded ? setShuffleOpen(true) : onShuffleAll())}
            >
              {shufflingAll ? (
                <Spinner className="mr-1.5 size-3.5" />
              ) : (
                <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
              )}
              {tl("shuffleAll")}
            </Button>
            <ConfirmDialog
              open={shuffleOpen}
              onOpenChange={setShuffleOpen}
              intent={{
                title: tl("shuffleTitle"),
                description: tl("shuffleDescription"),
                confirmLabel: tl("shuffleConfirm"),
                tone: "danger"
              }}
              pending={shufflingAll}
              onConfirm={() => {
                setShuffleOpen(false);
                onShuffleAll();
              }}
            />
          </>
        ) : null}

        {canWrite ? (
          <Button
            type="button"
            className="h-9 shrink-0"
            disabled={game == null}
            onClick={onOpenPool}
          >
            <UserPlus className="mr-1.5 size-3.5" aria-hidden="true" />
            Add players
          </Button>
        ) : null}

        {canWrite || offerDelete ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-9 w-9 shrink-0"
                disabled={game == null}
                aria-label={th("more")}
              >
                <MoreHorizontal className="size-4" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {canWrite && onLobbyCountChange ? (
                <>
                  <DropdownMenuLabel className={EYEBROW_CLASS}>
                    {tl("countLabel")}
                  </DropdownMenuLabel>
                  <DropdownMenuRadioGroup
                    value={String(lobbyCount)}
                    onValueChange={(value) => {
                      if (Number(value) === lobbyCount) return;
                      // Dropping B throws its balance away and clears every pin, so
                      // it is the direction that asks; opening one costs nothing.
                      if (value === "1") setDropLobbyOpen(true);
                      else onLobbyCountChange(2);
                    }}
                  >
                    {([1, 2] as const).map((count) => (
                      <DropdownMenuRadioItem
                        key={count}
                        value={String(count)}
                        disabled={settingLobbyCount}
                      >
                        {tl("count", { count })}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
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
                    className="text-danger focus:text-danger"
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

      {canWrite && onLobbyCountChange ? (
        <ConfirmDialog
          open={dropLobbyOpen}
          onOpenChange={setDropLobbyOpen}
          intent={{
            title: tl("dropTitle"),
            description: tl("dropDescription"),
            confirmLabel: tl("dropConfirm"),
            tone: "danger"
          }}
          pending={settingLobbyCount}
          onConfirm={() => {
            setDropLobbyOpen(false);
            onLobbyCountChange(1);
          }}
        />
      ) : null}

      {offerDelete ? (
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
      ) : null}
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
  saving,
  onSetSelfService
}: Readonly<{
  game: CustomGame;
  saving: boolean;
  onSetSelfService: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
}>) {
  const t = useTranslations("mixes.self");
  const mode = game.self_signup;
  const open = mode !== "closed";
  const stateLabel = t(`signupState.${mode}`);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label={t("signupTrigger", { mode: stateLabel })}
          className="h-9 shrink-0 gap-2"
        >
          <span className={EYEBROW_CLASS}>{t("signupLabel")}</span>
          <span
            aria-hidden="true"
            className={cn("size-1.5 shrink-0 rounded-full", SIGNUP_DOT[mode])}
          />
          {stateLabel}
          <ChevronDown className="size-3.5 text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22rem] space-y-3 p-3">
        <Segmented
          label={t("signupLabel")}
          options={[
            { value: "closed", label: t("signupState.closed") },
            { value: "open", label: t("signupOpen") }
          ]}
          value={open ? "open" : "closed"}
          disabled={saving}
          onChange={(value) => {
            if ((value === "open") === open) return;
            onSetSelfService({ self_signup: value === "open" ? "pool" : "closed" });
          }}
        />

        {open ? (
          <div className="space-y-2">
            <span className={EYEBROW_CLASS}>{t("signupWhere")}</span>
            <Segmented
              label={t("signupWhere")}
              options={SIGNUP_DESTINATIONS.map((value) => ({ value, label: t(`signup.${value}`) }))}
              value={mode}
              disabled={saving}
              onChange={(value) => onSetSelfService({ self_signup: value as MixSelfSignup })}
            />
          </div>
        ) : null}
        <p className="text-label text-[color:var(--aqt-fg-dim)]">{t(`signupHint.${mode}`)}</p>

        <div className="flex items-center gap-2 border-t border-[color:var(--aqt-border)] pt-3">
          <Switch
            checked={game.self_role_edit}
            disabled={saving}
            aria-label={t("roleEdit")}
            onCheckedChange={(checked) => onSetSelfService({ self_role_edit: checked })}
          />
          <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("roleEdit")}</span>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Segmented({
  label,
  options,
  value,
  disabled,
  onChange
}: Readonly<{
  label: string;
  options: readonly { value: string; label: string }[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <div role="radiogroup" aria-label={label} className={cn(segmentedFrame, "flex w-full")}>
      {options.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            data-state={selected ? "on" : "off"}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(toggleVariants({ variant: "pill" }), "flex-1 whitespace-nowrap px-2")}
          >
            {option.label}
          </button>
        );
      })}
    </div>
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
  // lobby letter only when the mix runs two lobbies, since with one it says
  // nothing. The slot is `lineup:<lobby_index>:<game number>`.
  const labelOf = (post: CustomGameDiscordPost) => {
    if (post.slot === "signup") return t("posts.signup");
    const [prefix, lobby, match] = post.slot.split(":");
    if (prefix !== "lineup") return post.slot;
    return game.lobby_count === 2
      ? t("posts.lineupLobby", { lobby: String.fromCharCode(65 + Number(lobby)), match })
      : t("posts.lineup", { match });
  };

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            aria-label={t("discord.trigger", { status: statusLabel })}
            className={cn(
              "h-9 shrink-0 gap-2",
              failed && "border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)]"
            )}
          >
            <span className={EYEBROW_CLASS}>{t("discord.label")}</span>
            {status === "pending" || status === "deleting" ? (
              <Spinner className="size-3.5" />
            ) : null}
            {status === "posted" ? (
              <CheckCircle2 className="size-3.5 text-[color:var(--aqt-teal)]" aria-hidden="true" />
            ) : null}
            {failed ? (
              <AlertTriangle className="size-3.5 text-[color:var(--aqt-rose)]" aria-hidden="true" />
            ) : null}
            <span className={status ? POST_STATUS_TONE[status] : "text-[color:var(--aqt-fg-dim)]"}>
              {statusLabel}
            </span>
            <ChevronDown className="size-3.5 text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[22rem] space-y-3 p-3">
          {onPostSignup ? (
            <div className="space-y-2">
              <span className={EYEBROW_CLASS}>{t("posts.signup")}</span>
              <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("discord.hint")}</p>
              <SignupPostStatus post={signupPost} />
              {hasChannel ? (
                <>
                  <Button
                    type="button"
                    // Re-posting a card that is up is a repair, not the next step.
                    variant={!closed && isLive(signupPost) ? "outline" : "default"}
                    className="h-9 w-full"
                    disabled={posting}
                    onClick={() => onPostSignup(postModeOf(game.self_signup))}
                  >
                    {posting ? (
                      <Spinner className="mr-1.5 size-3.5" />
                    ) : (
                      <Send className="mr-1.5 size-3.5" aria-hidden="true" />
                    )}
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
              <span className={EYEBROW_CLASS}>{t("discord.allPosts")}</span>
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
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 shrink-0 text-[color:var(--aqt-fg-muted)] hover:text-rose-200"
                        disabled={post.status === "deleting"}
                        aria-label={t("posts.delete", { label })}
                        onClick={() => {
                          setOpen(false);
                          setConfirming(post);
                        }}
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </Button>
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
