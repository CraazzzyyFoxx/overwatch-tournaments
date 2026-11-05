// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { isJobOfNode, useBalancerRealtime } from "./useBalancerRealtime";

const mocks = vi.hoisted(() => ({
  handler: null as null | ((event: { event_type: string; data: unknown }) => void),
  getBalanceJobResult: vi.fn(),
  append: vi.fn()
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() })
}));
vi.mock("@/hooks/useInvalidation", () => ({ useInvalidation: () => {} }));
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (_topic: string | null, handler: typeof mocks.handler) => {
    mocks.handler = handler;
  }
}));
vi.mock("@/stores/realtime.store", () => ({
  useRealtimeStore: (select: (state: unknown) => unknown) =>
    select({ connectionState: "connected", topicErrors: {} })
}));
vi.mock("@/services/realtime.service", () => ({ realtimeClient: { resubscribe: vi.fn() } }));
vi.mock("@/services/balancer.service", () => ({
  default: { getBalanceJobResult: (...args: unknown[]) => mocks.getBalanceJobResult(...args) }
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn() } }));
vi.mock("./balancer-job-result", () => ({
  appendGeneratedVariants: (...args: unknown[]) => mocks.append(...args)
}));

const job = (formation_node_id?: number | null) => ({
  job_id: "j",
  status: "succeeded",
  formation_node_id
});

describe("isJobOfNode", () => {
  it("ignores a job of another formation node", () => {
    expect(isJobOfNode(job(1), 2)).toBe(false);
  });

  it("follows the job of the node on screen", () => {
    expect(isJobOfNode(job(2), 2)).toBe(true);
  });

  it("follows an event that names no node", () => {
    expect(isJobOfNode(job(null), 2)).toBe(true);
    expect(isJobOfNode(job(), 2)).toBe(true);
  });
});

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

function mountHook(node: number) {
  const options = {
    tournamentId: 5,
    dispatchJob: vi.fn(),
    setVariants: vi.fn(),
    setActiveVariantId: vi.fn(),
    setPresence: vi.fn()
  };
  function Harness({ node }: { node: number }) {
    useBalancerRealtime({ ...options, formationNodeId: node });
    return null;
  }
  const root = createRoot(document.createElement("div"));
  act(() => root.render(createElement(Harness, { node })));
  return {
    setNode: (next: number) => act(() => root.render(createElement(Harness, { node: next })))
  };
}

describe("a job result that resolves after the node changed", () => {
  it("is dropped instead of landing in the other node's variants", async () => {
    const deferred = Promise.withResolvers<unknown>();
    mocks.getBalanceJobResult.mockReturnValue(deferred.promise);
    mocks.append.mockClear();
    const { setNode } = mountHook(1);

    act(() => mocks.handler?.({ event_type: "balancer_job.succeeded", data: job(1) }));
    setNode(2);
    await act(async () => {
      deferred.resolve({ variants: [] });
      await deferred.promise;
    });

    expect(mocks.getBalanceJobResult).toHaveBeenCalledOnce();
    expect(mocks.append).not.toHaveBeenCalled();
  });

  it("is applied while the node is still the one it was made for", async () => {
    mocks.getBalanceJobResult.mockReset().mockResolvedValue({ variants: [] });
    mocks.append.mockClear();
    mountHook(1);

    await act(async () =>
      mocks.handler?.({ event_type: "balancer_job.succeeded", data: { ...job(1), job_id: "k" } })
    );

    expect(mocks.append).toHaveBeenCalledOnce();
  });
});
