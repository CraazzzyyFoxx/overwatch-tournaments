"use client";

import { useEffect, useEffectEvent, type DependencyList } from "react";

import { realtimeClient } from "@/services/realtime.service";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

export function useRealtimeTopic<TData>(
  topic: string | null | undefined,
  onEvent: (event: RealtimeEventEnvelope<TData>) => void,
  deps: DependencyList = [],
  onSubscribed?: () => void,
): void {
  const handleEvent = useEffectEvent(onEvent);
  const handleSubscribed = useEffectEvent(() => onSubscribed?.());

  useEffect(() => {
    if (!topic) {
      return;
    }

    return realtimeClient.subscribe<TData>(
      topic,
      (event) => {
        handleEvent(event);
      },
      () => {
        handleSubscribed();
      },
    );
  }, [topic, ...deps]);
}
