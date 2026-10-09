// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import messages from "@/i18n/messages/en.json";
import { ScrimCreateDialog } from "./ScrimCreateDialog";

const { lookup } = vi.hoisted(() => ({ lookup: vi.fn().mockResolvedValue([]) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/services/tournament.service", () => ({ default: { lookup } }));

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean; }
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

it("starts all-mode creation without a local fallback and scopes lookup only after explicit choice", async () => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
          <QueryClientProvider client={client}>
            <ScrimCreateDialog workspaceId={null} workspaces={[
              { id: 3, name: "Community A" }, { id: 4, name: "Community B" }
            ]} />
          </QueryClientProvider>
        </NextIntlClientProvider>
      );
    });
    await act(async () => {
      container.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const chooser = document.body.querySelector("select[required]") as HTMLSelectElement;
    expect(chooser).not.toBeNull();
    expect(chooser.value).toBe("");
    expect(lookup).not.toHaveBeenCalled();
    const submit = [...document.body.querySelectorAll("button")].find(
      (button) => button.textContent === messages.scrims.create.submit
    );
    expect(submit?.disabled).toBe(true);
    await act(async () => {
      chooser.value = "4";
      chooser.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(lookup).toHaveBeenCalledWith(4);
    expect(lookup).not.toHaveBeenCalledWith(3);
  } finally {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
  }
});
