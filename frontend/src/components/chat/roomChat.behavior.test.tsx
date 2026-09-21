// @vitest-environment happy-dom
//
// What actually breaks in a chat fed by two sources and gated by a server-side
// verdict: a live event must show up, the SAME message arriving twice (POST
// reply + socket, or a catch-up read) must not double-print, a viewer the room
// refuses must see no trace of the panel, and the three things the `viewer`
// block decides — composer, muted notice, moderation — must follow it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { encounterChatRoom } from "@/lib/chat-rooms";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

import { RoomChat } from "./RoomChat";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getEnvelope = vi.fn();
const postMessage = vi.fn();
const deleteMessage = vi.fn();

vi.mock("@/services/roomChat.service", () => ({
  default: {
    getEnvelope: (...args: unknown[]) => getEnvelope(...args),
    postMessage: (...args: unknown[]) => postMessage(...args),
    deleteMessage: (...args: unknown[]) => deleteMessage(...args),
    setSettings: vi.fn(),
    setMute: vi.fn(),
    clearMute: vi.fn()
  }
}));

/** Topic -> the panel's handler, so a test can push what the hub would. */
const realtimeHandlers = new Map<string, (event: RealtimeEventEnvelope<unknown>) => void>();
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (topic: string, onEvent: (event: RealtimeEventEnvelope<unknown>) => void) => {
    realtimeHandlers.set(topic, onEvent);
  }
}));
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: "authenticated", user: { id: 42 } })
}));
vi.mock("@/lib/notify", () => ({
  notify: { error: vi.fn(), apiError: vi.fn(), success: vi.fn(), info: vi.fn() }
}));

const CHAT = en.chat;
const ROOM = encounterChatRoom(4242);

function message(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    created_at: "2026-09-21T10:00:00Z",
    auth_user_id: 7,
    author_name: "Fox",
    author_role: "home" as const,
    body: "ready?",
    ...overrides
  };
}

function envelope(overrides: Record<string, unknown> = {}) {
  return {
    messages: [message()],
    settings: { spectators_can_read: false },
    viewer: { role: "home", can_write: true, can_moderate: false, muted_until: null },
    mutes: [],
    ...overrides
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  realtimeHandlers.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <RoomChat room={ROOM} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

async function push(event: Partial<RealtimeEventEnvelope<unknown>>) {
  await act(async () => {
    realtimeHandlers.get(ROOM.topic)?.({
      event_id: 0,
      event_type: "chat.message",
      schema_version: 1,
      occurred_at: "2026-09-21T10:01:00Z",
      actor_user_id: 42,
      data: message({ id: 2, author_name: "Rabbit", author_role: "away", body: "go" }),
      ...event
    } as RealtimeEventEnvelope<unknown>);
  });
  await settle(1);
}

describe("room chat", () => {
  it("appends a realtime chat.message to the list", async () => {
    getEnvelope.mockResolvedValue(envelope());
    await render();

    expect(container.textContent).toContain("ready?");
    expect(container.textContent).not.toContain("go");

    await push({});

    expect(container.textContent).toContain("go");
    expect(container.textContent).toContain("Rabbit");
  });

  it("does not duplicate a message already known by id", async () => {
    getEnvelope.mockResolvedValue(
      envelope({ messages: [message({ id: 9, body: "already here" })] })
    );
    await render();

    // Same id as the history row — the sender's own POST reply, or a catch-up
    // read that overlapped what is already on screen.
    await push({ data: message({ id: 9, body: "already here" }) });

    expect(container.textContent?.match(/already here/g)).toHaveLength(1);
  });

  it("removes a row on chat.message_deleted", async () => {
    getEnvelope.mockResolvedValue(envelope());
    await render();
    expect(container.textContent).toContain("ready?");

    await push({ event_type: "chat.message_deleted", data: { id: 1 } });

    expect(container.textContent).not.toContain("ready?");
  });

  it("renders nothing when the room refuses the viewer", async () => {
    getEnvelope.mockResolvedValue(null);
    await render();

    expect(container.textContent).toBe("");
    expect(container.querySelector("textarea")).toBeNull();
    expect(document.body.textContent).not.toContain(CHAT.title);
  });

  it("gives a spectator the read-only notice instead of a composer", async () => {
    getEnvelope.mockResolvedValue(
      envelope({
        viewer: { role: "spectator", can_write: false, can_moderate: false, muted_until: null }
      })
    );
    await render();

    expect(container.textContent).toContain("ready?");
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain(CHAT.readOnly);
  });

  it("tells a muted viewer when the mute lifts instead of showing a composer", async () => {
    getEnvelope.mockResolvedValue(
      envelope({
        viewer: {
          role: "home",
          can_write: false,
          can_moderate: false,
          muted_until: "2026-09-21T12:00:00Z"
        }
      })
    );
    await render();

    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain(CHAT.muted.split("{until}")[0].trim());
  });

  it("deletes a message through the service when a moderator asks", async () => {
    getEnvelope.mockResolvedValue(
      envelope({
        viewer: { role: "staff", can_write: true, can_moderate: true, muted_until: null }
      })
    );
    deleteMessage.mockResolvedValue(undefined);
    await render();

    const label = CHAT.deleteLabel.replace("{name}", "Fox");
    const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
    expect(button).not.toBeNull();

    await act(async () => {
      button?.click();
    });
    await settle();

    expect(deleteMessage).toHaveBeenCalledWith(ROOM, 1);
    expect(container.textContent).not.toContain("ready?");
  });
});
