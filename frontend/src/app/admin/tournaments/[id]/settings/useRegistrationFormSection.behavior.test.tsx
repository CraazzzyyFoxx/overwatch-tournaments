// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { AdminRegistrationFormUpsert } from "@/types/balancer-admin.types";
import {
  useRegistrationFormSection,
  type RegistrationFormSection
} from "./useRegistrationFormSection";

const getTournament = vi.fn();
const getRegistrationForm = vi.fn();
const upsertRegistrationForm = vi.fn();
vi.mock("@/services/admin.service", () => ({
  default: { getTournament: (...args: unknown[]) => getTournament(...args) }
}));
vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getRegistrationForm: (...args: unknown[]) => getRegistrationForm(...args),
    upsertRegistrationForm: (...args: unknown[]) => upsertRegistrationForm(...args)
  }
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let section: RegistrationFormSection;
let root: Root;
let container: HTMLDivElement;
let client: QueryClient;

function Consumer() {
  const value = useRegistrationFormSection(1);
  useEffect(() => {
    section = value;
  }, [value]);
  return null;
}

async function settle() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <Consumer />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  vi.resetAllMocks();
  getRegistrationForm.mockResolvedValue(null);
  upsertRegistrationForm.mockImplementation(async (_id, body: AdminRegistrationFormUpsert) => ({
    id: 1,
    tournament_id: 1,
    workspace_id: 1,
    version_id: 1,
    version_number: 1,
    stale_registrations: 0,
    ...body
  }));
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
});

describe("registration settings owner resolution", () => {
  it("cannot save an implicit default while pending, then saves a required Riot identity", async () => {
    const owner = Promise.withResolvers<unknown>();
    getTournament.mockReturnValue(owner.promise);
    await mount();
    expect(section.value).toBeNull();
    await act(async () => {
      section.patch({ show_ranks: true });
      section.save();
    });
    await settle();
    expect(upsertRegistrationForm).not.toHaveBeenCalled();

    await act(async () => owner.resolve({ id: 1, discipline: "lol", identity_provider: "riot" }));
    await settle();
    await act(async () => section.save());
    await settle();
    const body: AdminRegistrationFormUpsert = upsertRegistrationForm.mock.calls[0][1];
    expect(body.show_ranks).toBe(true);
    const fields = body.form_schema.sections.flatMap((entry) => entry.fields);
    expect(fields.find((field) => field.key === "identity_riot")?.required).toBe(true);
    expect(fields.some((field) => field.key === "identity_battlenet")).toBe(false);
  });

  it("leaves an absent form unavailable on owner error, and permits retry", async () => {
    getTournament.mockRejectedValueOnce(new Error("Owner unavailable")).mockResolvedValue({
      id: 1,
      discipline: "lol",
      identity_provider: "riot"
    });
    await mount();
    expect(section.value).toBeNull();
    expect(section.error?.message).toBe("Owner unavailable");
    await act(async () => section.save());
    expect(upsertRegistrationForm).not.toHaveBeenCalled();
    await act(async () => section.retry());
    await settle();
    expect(section.value?.form_schema.sections[0].fields[0].key).toBe("identity_riot");
  });

  it.each(["pending", "error"])(
    "preserves a loaded form while owner metadata is %s",
    async (state) => {
      if (state === "pending") getTournament.mockReturnValue(Promise.withResolvers().promise);
      else getTournament.mockRejectedValue(new Error("Owner unavailable"));
      getRegistrationForm.mockResolvedValue({
        id: 1,
        tournament_id: 1,
        workspace_id: 1,
        version_id: 1,
        version_number: 1,
        stale_registrations: 0,
        form_schema: {
          schema_version: 1,
          sections: [
            {
              key: "custom",
              fields: [
                {
                  key: "contact",
                  kind: "text",
                  required: true,
                  visibility: "organizers",
                  params: {}
                }
              ]
            }
          ]
        }
      });
      await mount();
      expect(section.value).not.toBeNull();
      await act(async () => section.patch({ show_ranks: true }));
      await act(async () => section.save());
      await settle();
      const body: AdminRegistrationFormUpsert = upsertRegistrationForm.mock.calls[0][1];
      expect(body.show_ranks).toBe(true);
      expect(body.form_schema.sections).toEqual([
        {
          key: "custom",
          fields: [
            {
              key: "contact",
              kind: "text",
              required: true,
              visibility: "organizers",
              params: {}
            }
          ]
        }
      ]);
    }
  );
});
