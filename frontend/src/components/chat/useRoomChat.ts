"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import type { ChatRoomDescriptor } from "@/lib/chat-rooms";
import roomChatService from "@/services/roomChat.service";
import type {
  ChatEnvelope,
  ChatEventData,
  ChatMessage,
  ChatMute,
  ChatSettings
} from "@/types/chat.types";

/** Server-side cap on a single message, mirrored for client-side guidance. */
export const MAX_CHAT_LENGTH = 500;

/**
 * Fold rows into the list. A message arrives at least twice — the sender gets
 * it as the POST reply AND over the socket — so `id` is the dedupe key. It is
 * also the server's total order, which is what the list is sorted by: a
 * catch-up batch is not guaranteed to land after what is already on screen.
 */
function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

export function useRoomChat(room: ChatRoomDescriptor) {
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const queryKey = ["room-chat", room.topic];

  const envelope = useQuery({
    queryKey,
    queryFn: () => roomChatService.getEnvelope(room),
    // A 403 is a verdict, not a hiccup: retrying it just delays hiding the panel.
    retry: false
  });

  /** Rewrite the cached envelope, unless the viewer has no envelope at all. */
  const patch = (update: (current: ChatEnvelope) => ChatEnvelope) => {
    queryClient.setQueryData<ChatEnvelope | null>(queryKey, (current) =>
      current == null ? current : update(current)
    );
  };

  /**
   * Re-read the room from the newest message on screen. This is the reconnect
   * path AND the repair for a dropped Redis publish (at-most-once pub/sub can
   * lose a frame with no disconnect at all), and it re-answers `viewer` and
   * `settings` from the server — including the 403 that hides the panel once an
   * organizer closes the room to spectators.
   */
  const refresh = async () => {
    const current = queryClient.getQueryData<ChatEnvelope | null>(queryKey);
    if (current == null) return; // not resolved, or already forbidden
    const fresh = await roomChatService.getEnvelope(room, {
      afterId: current.messages.at(-1)?.id
    });
    queryClient.setQueryData<ChatEnvelope | null>(queryKey, (previous) =>
      fresh == null || previous == null
        ? fresh
        : { ...fresh, messages: mergeMessages(previous.messages, fresh.messages) }
    );
  };

  const applyMessage = (message: ChatMessage) =>
    patch((current) => ({ ...current, messages: mergeMessages(current.messages, [message]) }));

  const applyDeleted = (messageId: number) =>
    patch((current) => ({
      ...current,
      messages: current.messages.filter((message) => message.id !== messageId)
    }));

  const applyMute = (mute: ChatMute) =>
    patch((current) => ({
      ...current,
      mutes: [...current.mutes.filter((row) => row.auth_user_id !== mute.auth_user_id), mute],
      viewer:
        mute.auth_user_id === user?.id
          ? { ...current.viewer, can_write: false, muted_until: mute.muted_until }
          : current.viewer
    }));

  const applyUnmute = (authUserId: number) =>
    patch((current) => ({
      ...current,
      mutes: current.mutes.filter((row) => row.auth_user_id !== authUserId),
      viewer:
        authUserId === user?.id
          ? // The mute was the only thing suppressing the write right, and the
            // right itself is the role's: everyone but a spectator may type.
            { ...current.viewer, can_write: current.viewer.role !== "spectator", muted_until: null }
          : current.viewer
    }));

  const applySettings = (settings: ChatSettings) =>
    patch((current) => ({ ...current, settings }));

  // Null until the envelope resolved: the gateway denies this topic to everyone
  // it also 403s, so subscribing first would cost a rejected frame and an ACL
  // query per spectator in the room.
  const topic = envelope.data != null ? room.topic : null;

  useRealtimeTopic<ChatEventData>(
    topic,
    (event) => {
      const data = event.data;
      switch (event.event_type) {
        case "chat.message": {
          // `ChatMessageRead`, dumped verbatim onto the event by the shared
          // service — the same rows the history read returns.
          const message = data as ChatMessage;
          applyMessage(message);
          return;
        }
        case "chat.message_deleted":
          if (data.id != null) applyDeleted(data.id);
          return;
        case "chat.muted": {
          // `ChatMuteRead`, likewise dumped verbatim.
          const mute = data as ChatMute;
          applyMute(mute);
          return;
        }
        case "chat.unmuted":
          if (data.auth_user_id != null) applyUnmute(data.auth_user_id);
          return;
        case "chat.visibility_changed":
          if (data.spectators_can_read == null) return;
          applySettings({ spectators_can_read: data.spectators_can_read });
          // The server drops a spectator's subscription on the same event, so
          // let it answer whether this viewer still has a room at all.
          if (envelope.data?.viewer.role === "spectator") void refresh();
          return;
        default:
          return;
      }
    },
    [],
    () => void refresh()
  );

  // No optimistic insert anywhere: the reply is the authoritative row and lands
  // through the same dedupe as the socket copy, so whichever arrives first wins
  // and the other is a no-op.
  const send = useMutation({
    mutationFn: (body: string) => roomChatService.postMessage(room, body),
    onSuccess: applyMessage
  });

  const remove = useMutation({
    mutationFn: (messageId: number) => roomChatService.deleteMessage(room, messageId),
    onSuccess: (_result, messageId) => applyDeleted(messageId)
  });

  const setVisibility = useMutation({
    mutationFn: (spectatorsCanRead: boolean) =>
      roomChatService.setSettings(room, spectatorsCanRead),
    onSuccess: applySettings
  });

  const mute = useMutation({
    mutationFn: ({ authUserId, minutes }: { authUserId: number; minutes: number | null }) =>
      roomChatService.setMute(room, authUserId, minutes),
    onSuccess: applyMute
  });

  const unmute = useMutation({
    mutationFn: (authUserId: number) => roomChatService.clearMute(room, authUserId),
    onSuccess: (_result, authUserId) => applyUnmute(authUserId)
  });

  return {
    messages: envelope.data?.messages ?? [],
    settings: envelope.data?.settings ?? null,
    viewer: envelope.data?.viewer ?? null,
    mutes: envelope.data?.mutes ?? [],
    /**
     * The envelope resolved. A 403, a pending load and a hard failure all read
     * as "no room here", and the panel renders nothing for all three: it must
     * not advertise a back channel it will not let the viewer read.
     */
    visible: envelope.data != null,
    send,
    remove,
    setVisibility,
    mute,
    unmute
  };
}
