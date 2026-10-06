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
  UserPlus,
} from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameDiscordPost, MixSelfSignup } from "@/services/custom-game.service";

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
  onShuffleAll,
}: Readonly<PickupMixHeaderProps>) {
  const t = useTranslations("mixes.self");
  const tl = useTranslations("mixes.lobbies");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dropLobbyOpen, setDropLobbyOpen] = useState(false);
  const [shuffleOpen, setShuffleOpen] = useState(false);
  // The workspace's channel is the only target a mix has -- with none, the
  // signup card has nowhere to go. Unlike the matchup post (which simply is
  // not offered), this one stays visible and says why: a host who opens
  // signup expects the Discord button to be there, and "missing" reads as a
  // bug where "disabled, because there is no channel" reads as an answer.
  const hasChannel = game?.settings.workspace_discord_channel_id != null;
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
            <div className="ml-auto flex flex-wrap items-center justify-end gap-2.5">
              <SignupPostStatus posts={discordPosts} />
              {onDeleteDiscordPost && discordPosts.length > 0 ? (
                <DiscordPostsMenu
                  posts={discordPosts}
                  lobbyCount={lobbyCount}
                  deleting={deletingDiscordPost}
                  onDelete={onDeleteDiscordPost}
                />
              ) : null}
              <Button
                type="button"
                variant="outline"
                className="h-9 shrink-0"
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
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Where the live signup post stands, next to the button that (re)posts it --
 * read off the NEWEST `mix.signup` row, the one a re-post just created. The
 * bot answers asynchronously, so the press alone tells the host nothing:
 * `pending` until the bot writes the row, then a link to the message, or the
 * reason Discord refused -- almost always the bot's permissions in the mix
 * channel, which the host fixes and then simply presses the button again.
 * `lost` is the command that expired in the queue before the bot ever saw
 * it: nothing reached Discord, and posting again is the whole remedy.
 *
 * The `role="status"` region stays mounted even while there is nothing to
 * say (never posted): screen readers only announce changes to a live region
 * that already existed, so mounting it together with `pending` would swallow
 * the first update. It is empty then, so nothing is seen or read.
 *
 * ponytail: the error rides on `title` (+ sr-only text) -- this header has no
 * tooltip; a Popover if hosts need to copy a long refusal.
 */
function SignupPostStatus({ posts }: Readonly<{ posts: readonly CustomGameDiscordPost[] }>) {
  const t = useTranslations("mixes.self");
  const post = posts.findLast((row) => row.kind === "mix.signup");
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
    <span role="status" className="flex items-center text-caption">
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
          className="flex items-center gap-1.5 text-[color:var(--aqt-teal)] hover:underline"
        >
          {posted}
          <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      ) : null}
      {status === "posted" && !post?.url ? (
        <span className="flex items-center gap-1.5 text-[color:var(--aqt-teal)]">{posted}</span>
      ) : null}
      {status === "failed" ? (
        <span className="flex items-center gap-1.5 text-[color:var(--aqt-rose)]" title={failedReason}>
          <AlertTriangle className="size-3.5" aria-hidden="true" />
          {t("post.failed")}
          <span className="sr-only">{failedReason}</span>
        </span>
      ) : null}
      {status === "lost" ? (
        <span className="flex items-center gap-1.5 text-[color:var(--aqt-rose)]" title={t("post.lostHint")}>
          <AlertTriangle className="size-3.5" aria-hidden="true" />
          {t("post.lost")}
          <span className="sr-only">{t("post.lostHint")}</span>
        </span>
      ) : null}
    </span>
  );
}

const POST_STATUS_TONE: Record<CustomGameDiscordPost["status"], string> = {
  pending: "text-[color:var(--aqt-fg-dim)]",
  deleting: "text-[color:var(--aqt-fg-dim)]",
  posted: "text-[color:var(--aqt-teal)]",
  failed: "text-[color:var(--aqt-rose)]",
  lost: "text-[color:var(--aqt-rose)]",
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
  onDelete,
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
            <span className="ml-1.5 text-caption tabular-nums text-[color:var(--aqt-fg-dim)]">{posts.length}</span>
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
            label: confirming ? postLabel(confirming) : "",
          }),
          confirmLabel: t("posts.deleteConfirm"),
          tone: "danger",
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
