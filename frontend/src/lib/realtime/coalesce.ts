/**
 * Coalescing primitives for realtime event handling: collapse a burst of
 * events into a single callback, either at the leading edge (fire
 * immediately, then suppress repeats for a cooldown window) or the trailing
 * edge (wait for a quiet period, resetting on every new `schedule()` call).
 *
 * Originally written for tournament bracket realtime updates, now the timing
 * layer under `useRealtimeCoalescedRefetch` and the route refresh of the public
 * tournament shell — neither coalescer is tournament-specific.
 */

export type CoalescerClock<TTimer> = {
  setTimeout: (callback: () => void, delayMs: number) => TTimer;
  clearTimeout: (timer: TTimer) => void;
};

export type Coalescer = {
  schedule: () => void;
  cancel: () => void;
};

export function createLeadingCoalescer<TTimer = ReturnType<typeof setTimeout>>(
  callback: () => void,
  windowMs: number,
  clock: CoalescerClock<TTimer> = {
    setTimeout: (scheduledCallback, scheduledDelay) =>
      setTimeout(scheduledCallback, scheduledDelay) as TTimer,
    clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  },
): Coalescer {
  let cooldownTimer: TTimer | null = null;
  let generation = 0;

  return {
    schedule: () => {
      if (cooldownTimer !== null) {
        return;
      }

      callback();
      const scheduledGeneration = generation;
      cooldownTimer = clock.setTimeout(() => {
        if (generation === scheduledGeneration) {
          cooldownTimer = null;
        }
      }, windowMs);
    },
    cancel: () => {
      generation += 1;
      if (cooldownTimer !== null) {
        clock.clearTimeout(cooldownTimer);
        cooldownTimer = null;
      }
    },
  };
}

export function createTrailingCoalescer<TTimer = ReturnType<typeof setTimeout>>(
  callback: () => void,
  delayMs: number,
  clock: CoalescerClock<TTimer> = {
    setTimeout: (scheduledCallback, scheduledDelay) =>
      setTimeout(scheduledCallback, scheduledDelay) as TTimer,
    clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  },
): Coalescer {
  let timer: TTimer | null = null;
  let generation = 0;

  return {
    schedule: () => {
      generation += 1;
      const scheduledGeneration = generation;
      if (timer !== null) {
        clock.clearTimeout(timer);
      }
      timer = clock.setTimeout(() => {
        if (generation !== scheduledGeneration) {
          return;
        }
        timer = null;
        callback();
      }, delayMs);
    },
    cancel: () => {
      generation += 1;
      if (timer !== null) {
        clock.clearTimeout(timer);
        timer = null;
      }
    },
  };
}
