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

/** The three signup modes, in the order a host widens access. */
const SELF_SIGNUP_OPTIONS: readonly MixSelfSignup[] = ["closed", "pool", "benched"];

/** The trigger's dot: shut, open straight into the pool, or open onto the bench. */
const SIGNUP_DOT: Record<MixSelfSignup, string> = {
  closed: "bg-[color:var(--aqt-fg-faint)]",
  pool: "bg-[color:var(--aqt-teal)]",
  benched: "bg-[color:var(--aqt-amber)]"
};

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
  /** Omitted -- no Discord posts menu (and so no way to delete a post). */
  onDeleteDiscordPost?: (postId: number) => void;
  deletingDiscordPost?: boolean;
  settingLobbyCount?: boolean;
  /** Omitted -- the lobby-count switch is not rendered. */
  onLobbyCountChange?: (lobbyCount: 1 | 2) => void;
  shufflingAll?: boolean;
  /** Omitted -- no shared reshuffle, matching a page that offers none. */
  onShuffleAll?: () => void;
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
  onDeleteDiscordPost,
  deletingDiscordPost = false,
  settingLobbyCount = false,
  onLobbyCountChange,
  shufflingAll = false,
  onShuffleAll
}: Readonly<PickupMixHeaderProps>) {
  const tl = useTranslations("mixes.lobbies");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dropLobbyOpen, setDropLobbyOpen] = useState(false);
  const [shuffleOpen, setShuffleOpen] = useState(false);
  const lobbyCount = game?.lobby_count ?? 1;
  // A lineup that was balanced and never played into the log: a shared
  // reshuffle would replace it with nothing left to record it from.
  const unrecorded = (game?.lobbies ?? []).some((lobby) => lobby.lineup_recorded === false);
  const discordPosts = game?.discord_posts ?? [];

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

      {canWrite && game != null && onSetSelfService ? (
        <SignupSettings
          game={game}
          saving={savingSelfService}
          onSetSelfService={onSetSelfService}
          onPostSignup={onPostSignup}
          posting={postingSignup}
        />
      ) : null}

      {canWrite && onDeleteDiscordPost && discordPosts.length > 0 ? (
        <DiscordPostsMenu
          posts={discordPosts}
          lobbyCount={lobbyCount}
          deleting={deletingDiscordPost}
          onDelete={onDeleteDiscordPost}
        />
      ) : null}

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

      {canWrite && onLobbyCountChange ? (
        <>
          <div
            role="group"
            aria-label={tl("countLabel")}
            className="flex h-9 shrink-0 items-center gap-0.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-1"
          >
            <span className={cn(EYEBROW_CLASS, "px-1")}>{tl("countLabel")}</span>
            {([1, 2] as const).map((count) => (
              <button
                key={count}
                type="button"
                aria-pressed={lobbyCount === count}
                disabled={game == null || settingLobbyCount}
                onClick={() => {
                  if (lobbyCount === count) return;
                  // Dropping B throws its balance away and clears every pin, so
                  // it is the direction that asks; opening one costs nothing.
                  if (count === 1) setDropLobbyOpen(true);
                  else onLobbyCountChange(2);
                }}
                className={cn(
                  "flex size-7 items-center justify-center rounded-md text-caption font-semibold tabular-nums transition-colors",
                  lobbyCount === count
                    ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                    : "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
                )}
              >
                {count}
              </button>
            ))}
          </div>
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
        </>
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
    </div>
  );
}

/**
 * How players get into this mix, behind one button: the signup mode, whether
 * they edit their own roles, and the Discord card that announces it. These
 * used to be a second header row that wrapped into a third on a laptop; they
 * are set a few times per mix, so they cost a click and give the row back.
 *
 * The trigger carries what a host checks at a glance -- the mode, and whether
 * the signup post landed -- so closing the popover hides no state. Every
 * control writes on change, as before: there is nothing to save or cancel.
 */
function SignupSettings({
  game,
  saving,
  onSetSelfService,
  onPostSignup,
  posting
}: Readonly<{
  game: CustomGame;
  saving: boolean;
  onSetSelfService: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
  /** Omitted -- no Discord section. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  posting: boolean;
}>) {
  const t = useTranslations("mixes.self");
  const mode = game.self_signup;
  const modeLabel = t(`signup.${mode}`);
  // The live signup post: the NEWEST `mix.signup` row, the one a re-post just created.
  const signupPost =
    (game.discord_posts ?? []).findLast((row) => row.kind === "mix.signup") ?? null;
  const postStatus = onPostSignup ? (signupPost?.status ?? null) : null;
  const postFailed = postStatus === "failed" || postStatus === "lost";
  // The workspace's channel is the only target a mix has -- with none, the
  // signup card has nowhere to go. Unlike the matchup post (which simply is
  // not offered), this one stays visible and says why: a host who opens
  // signup expects the Discord button to be there, and "missing" reads as a
  // bug where "disabled, because there is no channel" reads as an answer.
  const hasChannel = game.settings.workspace_discord_channel_id != null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label={
            postStatus
              ? t("signupTriggerPost", { mode: modeLabel, post: t(`post.${postStatus}`) })
              : t("signupTrigger", { mode: modeLabel })
          }
          className={cn(
            "h-9 shrink-0 gap-2",
            postFailed && "border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)]"
          )}
        >
          <span className={EYEBROW_CLASS}>{t("signupLabel")}</span>
          <span
            aria-hidden="true"
            className={cn("size-1.5 shrink-0 rounded-full", SIGNUP_DOT[mode])}
          />
          {modeLabel}
          {postStatus === "pending" || postStatus === "deleting" ? (
            <Spinner className="size-3.5" />
          ) : null}
          {postStatus === "posted" ? (
            <CheckCircle2 className="size-3.5 text-[color:var(--aqt-teal)]" aria-hidden="true" />
          ) : null}
          {postFailed ? (
            <AlertTriangle className="size-3.5 text-[color:var(--aqt-rose)]" aria-hidden="true" />
          ) : null}
          <ChevronDown className="size-3.5 text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22rem] space-y-3 p-3">
        <div className="space-y-2">
          <span className={EYEBROW_CLASS}>{t("signupWhere")}</span>
          <div
            role="radiogroup"
            aria-label={t("signupLabel")}
            className={cn(segmentedFrame, "flex w-full")}
          >
            {SELF_SIGNUP_OPTIONS.map((option) => {
              const selected = mode === option;
              return (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  data-state={selected ? "on" : "off"}
                  disabled={saving}
                  onClick={() => onSetSelfService({ self_signup: option })}
                  className={cn(
                    toggleVariants({ variant: "pill" }),
                    "flex-1 whitespace-nowrap px-2"
                  )}
                >
                  {t(`signup.${option}`)}
                </button>
              );
            })}
          </div>
          <p className="text-label text-[color:var(--aqt-fg-dim)]">{t(`signupHint.${mode}`)}</p>
        </div>

        <div className="flex items-center gap-2 border-t border-[color:var(--aqt-border)] pt-3">
          <Switch
            checked={game.self_role_edit}
            disabled={saving}
            aria-label={t("roleEdit")}
            onCheckedChange={(checked) => onSetSelfService({ self_role_edit: checked })}
          />
          <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("roleEdit")}</span>
        </div>

        {onPostSignup ? (
          <div className="space-y-2 border-t border-[color:var(--aqt-border)] pt-3">
            <span className={EYEBROW_CLASS}>{t("posts.menu")}</span>
            <SignupPostStatus post={signupPost} />
            <Button
              type="button"
              variant="outline"
              className="h-9 w-full"
              disabled={!hasChannel || posting}
              title={hasChannel ? undefined : t("noChannel")}
              // A closed mix has no mode to post yet, and the card's whole point
              // is to open signup -- so posting it from `closed` opens the pool,
              // the mode a host picks in every other case.
              onClick={() => onPostSignup(mode === "benched" ? "benched" : "pool")}
            >
              <Send className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("openInDiscord")}
            </Button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Where the live signup post stands, above the button that (re)posts it. The
 * bot answers asynchronously, so the press alone tells the host nothing:
 * `pending` until the bot writes the row, then a link to the message, or the
 * reason Discord refused -- almost always the bot's permissions in the mix
 * channel, which the host fixes and then simply presses the button again.
 * `lost` is the command that expired in the queue before the bot ever saw
 * it: nothing reached Discord, and posting again is the whole remedy.
 *
 * The `role="status"` region is mounted with the popover, before the host can
 * press Post, and stays mounted while there is nothing to say: screen readers
 * only announce changes to a live region that already existed, so mounting it
 * together with `pending` would swallow the first update.
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

const POST_STATUS_TONE: Record<CustomGameDiscordPost["status"], string> = {
  pending: "text-[color:var(--aqt-fg-dim)]",
  deleting: "text-[color:var(--aqt-fg-dim)]",
  posted: "text-[color:var(--aqt-teal)]",
  failed: "text-[color:var(--aqt-rose)]",
  lost: "text-[color:var(--aqt-rose)]"
};

/**
 * Every message the platform posted for this mix, one row each: what it is,
 * where it stands, a link to it, and the host's way to take it down. Delete
 * asks first -- the message disappears from the channel for everyone -- and
 * the confirm lives outside the popover, which closes as the dialog takes
 * focus. A row already `deleting` cannot be deleted twice.
 */
function DiscordPostsMenu({
  posts,
  lobbyCount,
  deleting,
  onDelete
}: Readonly<{
  posts: readonly CustomGameDiscordPost[];
  lobbyCount: number;
  deleting: boolean;
  onDelete: (postId: number) => void;
}>) {
  const t = useTranslations("mixes.self");
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<CustomGameDiscordPost | null>(null);
  // What a post is, from its slot: the signup card, or one lineup card -- the
  // lobby letter only when the mix runs two lobbies, since with one it says
  // nothing. The slot is `lineup:<lobby_index>:<game number>`.
  const postLabel = (post: CustomGameDiscordPost) => {
    if (post.slot === "signup") return t("posts.signup");
    const [prefix, lobby, match] = post.slot.split(":");
    if (prefix !== "lineup") return post.slot;
    return lobbyCount === 2
      ? t("posts.lineupLobby", { lobby: String.fromCharCode(65 + Number(lobby)), match })
      : t("posts.lineup", { match });
  };

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" className="h-9 shrink-0">
            {t("posts.menu")}
            <span className="ml-1.5 text-caption tabular-nums text-[color:var(--aqt-fg-dim)]">
              {posts.length}
            </span>
            <ChevronDown className="ml-1 size-3.5" aria-hidden="true" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-1">
          <ul aria-label={t("posts.menu")} className="max-h-72 space-y-0.5 overflow-y-auto">
            {posts.map((post) => {
              const label = postLabel(post);
              return (
                <li key={post.id} className="flex items-center gap-2 rounded-md px-2 py-1.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-caption text-[color:var(--aqt-fg)]">{label}</div>
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
        </PopoverContent>
      </Popover>
      <ConfirmDialog
        open={confirming != null}
        onOpenChange={(next) => {
          if (!next) setConfirming(null);
        }}
        intent={{
          title: t("posts.deleteTitle"),
          description: t("posts.deleteDescription", {
            label: confirming ? postLabel(confirming) : ""
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
    </>
  );
}
