import { parseApiError } from "@/lib/api-error";
import { apiFetch } from "@/lib/api-fetch";
import type { ChatRoomDescriptor } from "@/lib/chat-rooms";
import type { ChatEnvelope, ChatMessage, ChatMute, ChatSettings } from "@/types/chat.types";

class RoomChatService {
  /**
   * Everything the panel needs, in one round trip. `null` means 403 — the
   * viewer may not read this room, which is a normal outcome for a spectator
   * of a closed room and not a failure: the panel simply does not exist for
   * them. Every other non-2xx still throws an `ApiError`, so a real outage
   * stays distinguishable from "no chat for you".
   *
   * `afterId` is the catch-up read: only what was said after the newest
   * message already on screen.
   */
  async getEnvelope(
    room: ChatRoomDescriptor,
    options: { afterId?: number; limit?: number } = {}
  ): Promise<ChatEnvelope | null> {
    const response = await apiFetch(room.basePath, {
      query: { after_id: options.afterId, limit: options.limit ?? 50 },
      throwOnError: false
    });
    if (response.status === 403) return null;
    if (!response.ok) throw await parseApiError(response);
    return response.json();
  }

  async postMessage(room: ChatRoomDescriptor, body: string): Promise<ChatMessage> {
    const response = await apiFetch(room.basePath, { method: "POST", body: { body } });
    return response.json();
  }

  async deleteMessage(room: ChatRoomDescriptor, messageId: number): Promise<void> {
    await apiFetch(`${room.basePath}/${messageId}`, { method: "DELETE" });
  }

  async setSettings(
    room: ChatRoomDescriptor,
    spectatorsCanRead: boolean
  ): Promise<ChatSettings> {
    const response = await apiFetch(`${room.basePath}/settings`, {
      method: "PATCH",
      body: { spectators_can_read: spectatorsCanRead }
    });
    return response.json();
  }

  /** `minutes: null` mutes until an organizer lifts it. */
  async setMute(
    room: ChatRoomDescriptor,
    authUserId: number,
    minutes: number | null
  ): Promise<ChatMute> {
    const response = await apiFetch(`${room.basePath}/mutes/${authUserId}`, {
      method: "PUT",
      body: { minutes, reason: null }
    });
    return response.json();
  }

  async clearMute(room: ChatRoomDescriptor, authUserId: number): Promise<void> {
    await apiFetch(`${room.basePath}/mutes/${authUserId}`, { method: "DELETE" });
  }
}

const roomChatService = new RoomChatService();
export default roomChatService;
