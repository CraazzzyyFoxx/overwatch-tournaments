"use client";

import { ArrowUp, MessageCircle, MessageCircleDashed, ShieldOff, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Dock } from "@/components/ui/dock";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger
} from "@/components/ui/context-menu";
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageGroup,
  MessageHeader
} from "@/components/ui/message";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError } from "@/lib/api-error";
import type { ChatRoomDescriptor } from "@/lib/chat-rooms";
import { notify } from "@/lib/notify";
import type { ChatMessage } from "@/types/chat.types";

import { MAX_CHAT_LENGTH, useRoomChat } from "./useRoomChat";

/** Show the counter only once the cap is in sight. */
const COUNTER_AT = 50;

/**
 * A same-author streak breaks after this long, so one header never stands for
 * an hour of conversation.
 */
const STREAK_GAP_MS = 5 * 60 * 1000;

/**
 * Consecutive messages from one author, in order, as the rows a `MessageGroup`
 * takes: the header sits on the first of a streak and the avatar on the last,
 * the way a chat is read.
 */
function streaks(messages: ChatMessage[]): ChatMessage[][] {
  const grouped: ChatMessage[][] = [];
  for (const message of messages) {
    const streak = grouped.at(-1);
    const previous = streak?.at(-1);
    // `author_name` is a per-message snapshot, so it joins the key: a rename
    // mid-conversation must start a new streak or the new name never appears.
    const continues =
      streak != null &&
      previous != null &&
      previous.auth_user_id === message.auth_user_id &&
      previous.author_name === message.author_name &&
      Date.parse(message.created_at) - Date.parse(previous.created_at) < STREAK_GAP_MS;
    if (continues) streak.push(message);
    else grouped.push([message]);
  }
  return grouped;
}

/**
 * One letter for the avatar. A BattleTag's discriminator (`Fox#2130`) is not
 * part of the name, and the first letter of a Cyrillic nickname is a code point
 * rather than a `charAt`.
 */
function initial(name: string): string {
  return [...name.replace(/#.*$/u, "").trim()][0]?.toUpperCase() ?? "?";
}

/**
 * A live room's chat — the pre-game room's and the draft room's, the same
 * panel, told apart only by the room descriptor it is handed.
 *
 * Built on the shadcn `message` / `bubble` primitives: `Message` owns the row
 * (avatar, side, header, footer) and `Bubble` is the surface the text sits on,
 * so a sent message reads the way it does in every other chat instead of being
 * a coloured div this component styles itself.
 *
 * A viewer the room will not let read gets a 403 on the envelope and this
 * renders NOTHING — not an empty panel, not a locked one. The room must not
 * advertise a back channel it will not let them read. Everything else the
 * panel shows — composer or read-only note, delete and mute affordances, the
 * spectator switch — comes from the `viewer` the same envelope carries, so
 * there is no second round trip and no guess about what this account may do.
 */
export function RoomChat({ room }: Readonly<{ room: ChatRoomDescriptor }>) {
  const t = useTranslations("chat");
  const format = useFormatter();
  const { user } = useAuthProfile();
  const { messages, settings, viewer, mutes, visible, send, remove, setVisibility, mute, unmute } =
    useRoomChat(room);
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const hintId = useId();
  const counterId = useId();
  const switchId = useId();

  if (!visible || viewer == null || settings == null) return null;

  const trimmed = draft.trim();
  const remaining = MAX_CHAT_LENGTH - draft.length;
  const blocked = trimmed.length === 0 || send.isPending;

  /**
   * 429 is the throttle, 403 + `chat_muted` is a mute the envelope did not
   * know about yet (an organizer muted mid-compose). Anything else is a
   * failure the sender can only retry.
   */
  const sendFailure = (error: unknown) => {
    if (error instanceof ApiError) {
      if (error.status === 429) return t("throttled");
      if (error.status === 403 && error.details.some((detail) => detail.code === "chat_muted")) {
        return t("sendMuted");
      }
    }
    return t("sendFailed");
  };

  const submit = () => {
    if (blocked) return;
    send.mutate(trimmed, {
      onSuccess: () => setDraft(""),
      onError: (error) => notify.error(sendFailure(error))
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter is a newline. Never intercept a composition
    // commit (IME), which also arrives as Enter.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  const applyMute = (authUserId: number, minutes: number | null) =>
    mute.mutate({ authUserId, minutes }, { onError: () => notify.error(t("muteFailed")) });

  return (
    <Dock
      title={t("title")}
      icon={<MessageCircle className="size-4" aria-hidden />}
      hideLabel={t("hide")}
      // Open on arrival, unlike the broadcast dock: everyone this room lets
      // read is IN the room, and a captain who has to find the chat before the
      // opponent's "ready?" reaches them is worse off than before it floated.
      defaultOpen
      // Only an organizer sees the switch, and only they can act on it: the
      // server re-authorizes every live subscriber when it flips.
      actions={
        viewer.can_moderate ? (
          <label
            htmlFor={switchId}
            className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground"
          >
            {/* Dropped on a narrow PANEL, not a narrow viewport: the dock is
                22rem wherever the viewport can hold it, and a viewport
                breakpoint would keep the label and crush the title to
                "Чат ко…". */}
            <span className="hidden @min-[20rem]/panel:inline">{t("spectatorRead")}</span>
            <Switch
              id={switchId}
              aria-label={t("spectatorRead")}
              checked={settings.spectators_can_read}
              disabled={setVisibility.isPending}
              onCheckedChange={(checked) =>
                setVisibility.mutate(checked, {
                  onError: () => notify.error(t("visibilityFailed"))
                })
              }
            />
          </label>
        ) : null
      }
      // Taller than the default dock and capped by the viewport, so the
      // transcript scrolls inside the panel instead of running off the screen
      // on a laptop.
      className="@container/panel h-[min(32rem,calc(100dvh-6rem))] w-[min(22rem,calc(100vw-2rem))]"
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {/* `Conversation` is the stick-to-bottom scroller and already sets
              role="log" — it only needs a name, not a second live region. */}
        <Conversation aria-label={t("listLabel")}>
          <ConversationContent className="gap-4 p-3">
            {messages.length === 0 ? (
              <ConversationEmptyState
                title={t("empty")}
                description={t("emptyHint")}
                icon={<MessageCircleDashed className="size-5" aria-hidden />}
              />
            ) : (
              streaks(messages).map((streak) => {
                const author = streak[0];
                const isSelf = user != null && author.auth_user_id === user.id;
                // An author may always take their own words back; a moderator
                // may take anyone's.
                const canDelete = viewer.can_moderate || isSelf;
                const canMute = viewer.can_moderate && !isSelf;
                const isMuted = mutes.some((row) => row.auth_user_id === author.auth_user_id);

                return (
                  <MessageGroup key={author.id}>
                    {streak.map((message, index) => (
                      <Message key={message.id} align={isSelf ? "end" : "start"}>
                        {/* Empty on every row but the last: a zero-height
                              spacer that keeps the streak aligned with the one
                              avatar the group shows. */}
                        <MessageAvatar>
                          {index === streak.length - 1 ? (
                            <Avatar className="size-8">
                              {message.author_avatar_url ? (
                                // Decorative: the author's name is right
                                // above it, so alt text would only repeat.
                                <AvatarImage src={message.author_avatar_url} alt="" />
                              ) : null}
                              <AvatarFallback className="text-xs font-semibold">
                                {initial(message.author_name)}
                              </AvatarFallback>
                            </Avatar>
                          ) : null}
                        </MessageAvatar>
                        <MessageContent>
                          {index === 0 ? (
                            <MessageHeader className="gap-1.5">
                              <span className="min-w-0 truncate text-foreground">
                                {message.author_name}
                              </span>
                              <span aria-hidden>·</span>
                              <span className="shrink-0 uppercase">
                                {t(`role.${message.author_role}`)}
                              </span>
                            </MessageHeader>
                          ) : null}
                          {/* Right-click (long-press on touch, the menu key
                                on a keyboard) rather than a row of icons under
                                every message: moderation is rare and the
                                buttons cost more attention than they earn. The
                                bubble is focusable only when there is in fact
                                a menu behind it. */}
                          <ContextMenu>
                            <ContextMenuTrigger asChild disabled={!canDelete && !canMute}>
                              <Bubble
                                variant={isSelf ? "default" : "muted"}
                                tabIndex={canDelete || canMute ? 0 : undefined}
                                aria-haspopup={canDelete || canMute ? "menu" : undefined}
                                className="outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
                              >
                                {/* Plain text, always: chat bodies are never
                                      parsed as markup. The time rides inside
                                      the bubble, where every other chat puts
                                      it. */}
                                <BubbleContent className="flex flex-col gap-0.5">
                                  <span className="whitespace-pre-wrap">{message.body}</span>
                                  <time
                                    dateTime={message.created_at}
                                    // 0.85, not 0.7: at 12px the dimmer step
                                    // measured APCA |Lc| 54 on the sent
                                    // bubble, under the 60 non-body floor
                                    // this theme is verified against.
                                    className="self-end text-label leading-none tabular-nums opacity-85"
                                  >
                                    {format.dateTime(new Date(message.created_at), {
                                      hour: "2-digit",
                                      minute: "2-digit"
                                    })}
                                  </time>
                                </BubbleContent>
                              </Bubble>
                            </ContextMenuTrigger>
                            {canDelete || canMute ? (
                              <ContextMenuContent className="w-48">
                                <ContextMenuLabel className="truncate">
                                  {message.author_name}
                                </ContextMenuLabel>
                                {canDelete ? (
                                  <ContextMenuItem
                                    onSelect={() =>
                                      remove.mutate(message.id, {
                                        onError: () => notify.error(t("deleteFailed"))
                                      })
                                    }
                                  >
                                    <Trash2 className="mr-2 size-4" aria-hidden />
                                    {t("deleteAction")}
                                  </ContextMenuItem>
                                ) : null}
                                {canMute ? (
                                  <>
                                    <ContextMenuSeparator />
                                    {isMuted ? (
                                      <ContextMenuItem
                                        onSelect={() =>
                                          unmute.mutate(message.auth_user_id, {
                                            onError: () => notify.error(t("muteFailed"))
                                          })
                                        }
                                      >
                                        <ShieldOff className="mr-2 size-4" aria-hidden />
                                        {t("unmute")}
                                      </ContextMenuItem>
                                    ) : null}
                                    <ContextMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, 5)}
                                    >
                                      {t("mute5m")}
                                    </ContextMenuItem>
                                    <ContextMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, 60)}
                                    >
                                      {t("mute1h")}
                                    </ContextMenuItem>
                                    <ContextMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, null)}
                                    >
                                      {t("muteForever")}
                                    </ContextMenuItem>
                                  </>
                                ) : null}
                              </ContextMenuContent>
                            ) : null}
                          </ContextMenu>
                        </MessageContent>
                      </Message>
                    ))}
                  </MessageGroup>
                );
              })
            )}
          </ConversationContent>
          <ConversationScrollButton aria-label={t("jumpToLatest")} />
        </Conversation>
      </div>

      <div className="border-t border-[color:var(--aqt-border)] p-2">
        {viewer.can_write ? (
          <form
            className="w-full"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <label htmlFor={inputId} className="sr-only">
              {t("inputLabel")}
            </label>
            {/* One surface, the way shadcn's composer reads: the field has no
                  chrome of its own and the ring belongs to the group. */}
            <div className="flex flex-col rounded-xl border bg-background focus-within:ring-1 focus-within:ring-ring">
              <Textarea
                id={inputId}
                value={draft}
                rows={2}
                // Guidance, not the gate — the server rejects over-long text anyway.
                maxLength={MAX_CHAT_LENGTH}
                placeholder={t("placeholder")}
                // The key binding is described, not put in a `title`: a
                // tooltip reaches neither a keyboard nor a touch user.
                aria-describedby={remaining <= COUNTER_AT ? `${hintId} ${counterId}` : hintId}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onKeyDown}
                className="min-h-[2.75rem] resize-none border-0 bg-transparent text-base shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 sm:text-sm"
              />
              <div className="flex items-end justify-between gap-2 px-2 pb-2">
                <p id={hintId} className="sr-only">
                  {t("inputHint")}
                </p>
                {remaining <= COUNTER_AT ? (
                  <p id={counterId} className="text-label tabular-nums text-muted-foreground">
                    {t("remaining", { count: remaining })}
                  </p>
                ) : (
                  <span />
                )}
                <Button
                  type="submit"
                  size="icon"
                  className="size-8 rounded-full"
                  disabled={blocked}
                  aria-label={t("send")}
                >
                  <ArrowUp className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </form>
        ) : (
          // A spectator is told the room is read-only; anyone else who cannot
          // write is muted, because the write right is otherwise the role's.
          // An indefinite mute carries no expiry to show, so it says so.
          <p className="w-full text-center text-xs text-muted-foreground">
            {viewer.role === "spectator"
              ? t("readOnly")
              : viewer.muted_until != null
                ? t("muted", {
                    until: format.dateTime(new Date(viewer.muted_until), {
                      hour: "2-digit",
                      minute: "2-digit"
                    })
                  })
                : t("mutedIndefinite")}
          </p>
        )}
      </div>
    </Dock>
  );
}
