import { create } from "zustand";

import type { RealtimeConnectionState } from "@/types/realtime.types";

type RealtimeStore = {
  connectionState: RealtimeConnectionState;
  lastEventIdByTopic: Record<string, number>;
  setConnectionState: (connectionState: RealtimeConnectionState) => void;
  setLastEventId: (topic: string, eventId: number) => void;
};

export const useRealtimeStore = create<RealtimeStore>((set) => ({
  connectionState: "idle",
  lastEventIdByTopic: {},
  setConnectionState: (connectionState) => set({ connectionState }),
  setLastEventId: (topic, eventId) =>
    set((state) => ({
      lastEventIdByTopic: {
        ...state.lastEventIdByTopic,
        [topic]: Math.max(state.lastEventIdByTopic[topic] ?? 0, eventId)
      }
    }))
}));
