// @vitest-environment happy-dom
//
// Organizer notes panel. Pinned:
//  1. edit/attach show only on the viewer's OWN notes; delete also for a moderator;
//  2. a new note is created first and its files uploaded after, against the new id;
//  3. a file over the server's cap never starts an upload.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RegistrationNote } from "@/types/registration-note.types";
import { RegistrationNotesPanel } from "./RegistrationNotesPanel";
import type * as noteServiceModule from "@/services/registration-note.service";

function flush(): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const list = vi.fn();
const create = vi.fn();
const uploadAttachment = vi.fn();
const notifyError = vi.fn();

vi.mock("@/services/registration-note.service", async (importOriginal) => {
  const actual = await importOriginal<typeof noteServiceModule>();
  return {
    ...actual,
    default: {
      list: (...args: unknown[]) => list(...args),
      create: (...args: unknown[]) => create(...args),
      uploadAttachment: (...args: unknown[]) => uploadAttachment(...args),
      update: vi.fn(),
      remove: vi.fn(),
      removeAttachment: vi.fn(),
      attachmentUrl: vi.fn()
    }
  };
});
vi.mock("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => ({ user: { id: 1 } }) }));
vi.mock("@/lib/notify", () => ({ notify: { error: (m: string) => notifyError(m), success: vi.fn() } }));

function note(id: number, authorId: number): RegistrationNote {
  return {
    id,
    registration_id: 5,
    registration_team_id: null,
    author_id: authorId,
    author_username: `user${authorId}`,
    body: `note ${id}`,
    created_at: "2026-11-14T10:00:00Z",
    edited_at: null,
    attachments: []
  };
}

let container: HTMLDivElement;
let root: Root;

async function render(props: { canWrite: boolean; canModerate: boolean }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <RegistrationNotesPanel tournamentId={9} target={{ registrationId: 5 }} {...props} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await flush();
  });
}

const labelled = (label: string) => container.querySelectorAll(`[aria-label="${label}"]`);

function pick(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, "files", { value: files, configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("RegistrationNotesPanel", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    list.mockResolvedValue([note(1, 1), note(2, 2)]);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("offers edit and attach on the viewer's own note only, delete on others' only to a moderator", async () => {
    await render({ canWrite: true, canModerate: false });
    expect(labelled("Edit note")).toHaveLength(1);
    expect(labelled("Attach a file")).toHaveLength(1);
    expect(labelled("Delete note")).toHaveLength(1);

    act(() => root.unmount());
    root = createRoot(container);
    await render({ canWrite: true, canModerate: true });
    expect(labelled("Edit note")).toHaveLength(1);
    expect(labelled("Delete note")).toHaveLength(2);
  });

  it("creates the note, then uploads its files to the new note; an oversized file is refused up front", async () => {
    create.mockResolvedValue(note(3, 1));
    uploadAttachment.mockResolvedValue(note(3, 1));
    await render({ canWrite: true, canModerate: false });

    const composerInput = container.querySelectorAll<HTMLInputElement>('input[type="file"][multiple]')[0];
    const ok = new File(["x"], "proof.png", { type: "image/png" });
    const huge = new File(["x"], "huge.zip");
    Object.defineProperty(huge, "size", { value: 11 * 1024 * 1024 });
    await act(async () => pick(composerInput, [ok, huge]));
    expect(notifyError).toHaveBeenCalledWith("huge.zip is larger than 10 MB.");

    const textarea = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="New note"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "  Called the captain  ");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const addButton = [...container.querySelectorAll("button")].find((b) => b.textContent === "Add note")!;
    await act(async () => addButton.click());
    await act(async () => {
      await flush();
    });

    expect(create).toHaveBeenCalledWith(9, { registrationId: 5 }, "Called the captain");
    expect(uploadAttachment).toHaveBeenCalledTimes(1);
    expect(uploadAttachment).toHaveBeenCalledWith(9, 3, ok);
  });
});
