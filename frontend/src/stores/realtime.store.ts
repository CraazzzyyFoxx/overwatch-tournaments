import { create } from "zustand";

import type { RealtimeConnectionState } from "@/types/realtime.types";

/** A rejected subscription (e.g. `forbidden`), surfaced so the UI can react
 * instead of silently hanging. Cleared once the topic subscribes successfully. */
export type TopicSubscriptionError = { code: string; message: string };

type RealtimeStore = {
  connectionState: RealtimeConnectionState;
  lastEventIdByTopic: Record<string, number>;
  topicErrors: Record<string, TopicSubscriptionError>;
  setConnectionState: (connectionState: RealtimeConnectionState) => void;
  setLastEventId: (topic: string, eventId: number) => void;
  setTopicError: (topic: string, error: TopicSubscriptionError | null) => void;
};

export const useRealtimeStore = create<RealtimeStore>((set) => ({
  connectionState: "idle",
  lastEventIdByTopic: {},
  topicErrors: {},
  setConnectionState: (connectionState) => set({ connectionState }),
  setLastEventId: (topic, eventId) =>
    set((state) => ({
      lastEventIdByTopic: {
        ...state.lastEventIdByTopic,
        [topic]: Math.max(state.lastEventIdByTopic[topic] ?? 0, eventId)
      }
    })),
  setTopicError: (topic, error) =>
    set((state) => {
      const next = { ...state.topicErrors };
      if (error) {
        next[topic] = error;
      } else {
        delete next[topic];
      }
      return { topicErrors: next };
    })
}));
