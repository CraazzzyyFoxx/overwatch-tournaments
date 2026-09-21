"use client";

import { SendHorizonal, ShieldOff, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageHeader } from "@/components/ai-elements/message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError } from "@/lib/api-error";
import type { ChatRoomDescriptor } from "@/lib/chat-rooms";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";

import { MAX_CHAT_LENGTH, useRoomChat } from "./useRoomChat";

/** Show the counter only once the cap is in sight. */
const COUNTER_AT = 50;

/**
 * A live room's chat — the pre-game room's and the draft room's, the same
 * panel, told apart only by the room descriptor it is handed.
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
    <section
      className={cn(
        "flex h-[26rem] flex-col overflow-hidden rounded-xl border bg-card lg:h-[32rem]",
        className
      )}
      aria-label={t("title")}
    >
      <div className="flex items-center gap-3 border-b px-3 py-2">
        <h2 className="min-w-0 flex-1 truncate text-label uppercase tracking-label text-muted-foreground">
          {t("title")}
        </h2>
        {/* Only an organizer sees the switch, and only they can act on it: the
            server re-authorizes every live subscriber when it flips. */}
        {viewer.can_moderate ? (
          <label
            htmlFor={switchId}
            className="flex shrink-0 items-center gap-2 text-label uppercase tracking-label text-muted-foreground"
          >
            {/* The label text is the first thing to go when the panel is a
                phone's width: the switch keeps the same name through
                aria-label, and the room title stops being crushed to "ROO…". */}
            <span className="hidden sm:inline">{t("spectatorRead")}</span>
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
      </div>

      {/* `Conversation` is the stick-to-bottom scroller and already sets
          role="log" — it only needs a name, not a second live region. */}
      <Conversation aria-label={t("listLabel")}>
        <ConversationContent className="gap-3 p-3">
          {messages.length === 0 ? (
            <ConversationEmptyState title={t("empty")} description={t("emptyHint")} />
          ) : (
            messages.map((message) => {
              const isSelf = user != null && message.auth_user_id === user.id;
              // An author may always take their own words back; a moderator may
              // take anyone's.
              const canDelete = viewer.can_moderate || isSelf;
              const canMute = viewer.can_moderate && !isSelf;
              const isMuted = mutes.some((row) => row.auth_user_id === message.auth_user_id);

              return (
                <Message key={message.id} from={isSelf ? "self" : "peer"}>
                  {/* Wraps rather than squeezes: with a delete and a mute
                      button in the row, a fixed line would truncate the author
                      to one letter before the buttons gave up any width. */}
                  <MessageHeader className="flex-wrap">
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {message.author_name}
                    </span>
                    <Badge
                      variant="outline"
                      className="shrink-0 px-1.5 py-0 text-label font-normal"
                    >
                      {t(`role.${message.author_role}`)}
                    </Badge>
                    <time dateTime={message.created_at} className="shrink-0 tabular-nums">
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
                        className="h-6 w-6 shrink-0"
                        aria-label={t("deleteLabel", { name: message.author_name })}
                        disabled={remove.isPending}
                        onClick={() =>
                          remove.mutate(message.id, {
                            onError: () => notify.error(t("deleteFailed"))
                          })
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    ) : null}
                    {canMute ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 shrink-0"
                            aria-label={t("muteLabel", { name: message.author_name })}
                          >
                            <ShieldOff className="h-3.5 w-3.5" aria-hidden />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
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
                  </MessageHeader>
                  {/* Plain text, always: chat bodies are never parsed as markup. */}
                  <MessageContent>{message.body}</MessageContent>
                </Message>
              );
            })
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {viewer.can_write ? (
        <form
          className="flex items-end gap-2 border-t p-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label htmlFor={inputId} className="sr-only">
            {t("inputLabel")}
          </label>
          <div className="min-w-0 flex-1">
            <Textarea
              id={inputId}
              value={draft}
              rows={2}
              // Guidance, not the gate — the server rejects over-long text anyway.
              maxLength={MAX_CHAT_LENGTH}
              placeholder={t("placeholder")}
              // The key binding lives in the tooltip, not the placeholder: at a
              // phone's panel width the combined string wrapped to three lines
              // and the last one was clipped by the fixed-height composer.
              title={t("inputHint")}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              className="min-h-[2.75rem] resize-none"
            />
            {remaining <= COUNTER_AT ? (
              <p className="mt-1 text-right text-label tabular-nums text-muted-foreground">
                {t("remaining", { count: remaining })}
              </p>
            ) : null}
          </div>
          <Button type="submit" size="icon" disabled={blocked} aria-label={t("send")}>
            <SendHorizonal className="h-4 w-4" aria-hidden />
          </Button>
        </form>
      ) : (
        // A spectator is told the room is read-only; anyone else who cannot
        // write is muted, because the write right is otherwise the role's.
        // An indefinite mute carries no expiry to show, so it says so.
        <p className="border-t px-3 py-2 text-center text-xs text-muted-foreground">
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
    </section>
  );
}
