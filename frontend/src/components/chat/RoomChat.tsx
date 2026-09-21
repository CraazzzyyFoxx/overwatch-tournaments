"use client";

import { ArrowUp, MessageCircleDashed, ShieldOff, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageFooter,
  MessageGroup,
  MessageHeader
} from "@/components/ui/message";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError } from "@/lib/api-error";
import type { ChatRoomDescriptor } from "@/lib/chat-rooms";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
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
export function RoomChat({
  room,
  className
}: Readonly<{ room: ChatRoomDescriptor; className?: string }>) {
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
    <Card
      className={cn(
        "@container/panel flex h-[26rem] flex-col overflow-hidden lg:h-[32rem]",
        className
      )}
      aria-label={t("title")}
      asChild
    >
      <section>
        <CardHeader className="flex-row items-center gap-3 space-y-0 border-b px-3 py-2.5">
          <CardTitle asChild className="min-w-0 flex-1 truncate text-sm">
            <h2>{t("title")}</h2>
          </CardTitle>
          {/* Only an organizer sees the switch, and only they can act on it: the
              server re-authorizes every live subscriber when it flips. */}
          {viewer.can_moderate ? (
            <label
              htmlFor={switchId}
              className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground"
            >
              {/* Dropped on a narrow PANEL, not a narrow viewport: at 1024px+
                  this sits in a 22rem rail, where a viewport breakpoint would
                  keep the label and crush the title to "Чат ко…". */}
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
          ) : null}
        </CardHeader>

        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
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
                            <Bubble variant={isSelf ? "default" : "muted"}>
                              {/* Plain text, always: chat bodies are never
                                  parsed as markup. */}
                              <BubbleContent className="whitespace-pre-wrap">
                                {message.body}
                              </BubbleContent>
                            </Bubble>
                            {/* Time and moderation below the bubble, never in
                                the header row: with two icon buttons up there
                                the author's name wrapped to a second line and
                                the controls moved per row. */}
                            <MessageFooter className="gap-3">
                              <time
                                dateTime={message.created_at}
                                className="shrink-0 font-normal tabular-nums"
                              >
                                {format.dateTime(new Date(message.created_at), {
                                  hour: "2-digit",
                                  minute: "2-digit"
                                })}
                              </time>
                              {canDelete ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  className="size-7 shrink-0"
                                  aria-label={t("deleteLabel", { name: message.author_name })}
                                  disabled={remove.isPending && remove.variables === message.id}
                                  onClick={() =>
                                    remove.mutate(message.id, {
                                      onError: () => notify.error(t("deleteFailed"))
                                    })
                                  }
                                >
                                  <Trash2 className="size-3.5" aria-hidden />
                                </Button>
                              ) : null}
                              {canMute ? (
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon"
                                      className="size-7 shrink-0"
                                      aria-label={t("muteLabel", { name: message.author_name })}
                                    >
                                      <ShieldOff className="size-3.5" aria-hidden />
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align={isSelf ? "end" : "start"}>
                                    {isMuted ? (
                                      <DropdownMenuItem
                                        onSelect={() =>
                                          unmute.mutate(message.auth_user_id, {
                                            onError: () => notify.error(t("muteFailed"))
                                          })
                                        }
                                      >
                                        {t("unmute")}
                                      </DropdownMenuItem>
                                    ) : null}
                                    <DropdownMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, 5)}
                                    >
                                      {t("mute5m")}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, 60)}
                                    >
                                      {t("mute1h")}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                      onSelect={() => applyMute(message.auth_user_id, null)}
                                    >
                                      {t("muteForever")}
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              ) : null}
                            </MessageFooter>
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
        </CardContent>

        <CardFooter className="border-t p-2">
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
        </CardFooter>
      </section>
    </Card>
  );
}
