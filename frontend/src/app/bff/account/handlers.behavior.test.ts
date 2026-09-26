// These five handlers are a thin, uniform shell around identity-svc
// (`_lib.ts`), and the whole contract is what they DON'T change: the upstream
// status, the upstream body, and the order in which their own refusals answer.
// Every case here is a shape a screen reads — `use-account-sessions` and
// `use-account-api-keys` branch on exactly these statuses and `detail` strings.
import { beforeEach, describe, expect, it, vi } from "vitest";

let cookieValue: string | undefined = "tok";
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => (cookieValue ? { value: cookieValue } : undefined) })
}));

const calls: Array<[string, RequestInit]> = [];
let reply: Response = new Response(JSON.stringify({ ok: true }), { status: 200 });

beforeEach(() => {
  calls.length = 0;
  cookieValue = "tok";
  globalThis.fetch = vi.fn(async (url: unknown, init: unknown) => {
    calls.push([String(url), init as RequestInit]);
    return reply;
  }) as unknown as typeof fetch;
});

describe("bff account handlers", () => {
  it("401s without a session cookie", async () => {
    cookieValue = undefined;
    const { GET } = await import("./sessions/route");
    const res = await GET();
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ detail: "Unauthorized" });
    expect(calls.length).toBe(0);
  });

  it("forwards the bearer and passes the upstream status through", async () => {
    reply = new Response(JSON.stringify({ detail: "nope" }), { status: 403 });
    const { GET } = await import("./sessions/route");
    const res = await GET();
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ detail: "nope" });
    expect(calls[0][0]).toMatch(/\/api\/v1\/auth\/sessions$/);
    expect((calls[0][1].headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("returns a bodiless 204 for a revoke", async () => {
    reply = new Response(null, { status: 204 });
    const { DELETE } = await import("./sessions/[sessionId]/route");
    const res = await DELETE(new Request("http://x"), {
      params: Promise.resolve({ sessionId: "a b" })
    });
    expect(res.status).toBe(204);
    expect(calls[0][0]).toMatch(/\/sessions\/a%20b$/);
    expect(calls[0][1].method).toBe("DELETE");
  });

  it("falls back to the route's detail when the upstream body is not JSON", async () => {
    reply = new Response("<html>502</html>", { status: 502 });
    const { GET } = await import("./sessions/route");
    const res = await GET();
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ detail: "Failed to load sessions" });
  });

  it("500s with the route's detail when the upstream call throws", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("econnrefused");
    }) as unknown as typeof fetch;
    const { GET } = await import("./sessions/route");
    const res = await GET();
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ detail: "Failed to load sessions" });
  });

  it("401s before complaining about a missing workspace_id", async () => {
    cookieValue = undefined;
    const { GET } = await import("./api-keys/route");
    const { NextRequest } = await import("next/server");
    const res = await GET(new NextRequest("http://x/bff/account/api-keys"));
    expect(res.status).toBe(401);
  });

  it("400s a signed-in caller with no workspace_id", async () => {
    const { GET } = await import("./api-keys/route");
    const { NextRequest } = await import("next/server");
    const res = await GET(new NextRequest("http://x/bff/account/api-keys"));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ detail: "workspace_id is required" });
  });

  it("forwards every query param and the verbatim create body", async () => {
    reply = new Response(JSON.stringify({ id: 1 }), { status: 201 });
    const { GET, POST } = await import("./api-keys/route");
    const { NextRequest } = await import("next/server");

    await GET(new NextRequest("http://x/bff/account/api-keys?workspace_id=3&page=2"));
    expect(calls[0][0]).toMatch(/\/api-keys\?workspace_id=3&page=2$/);

    const res = await POST(
      new NextRequest("http://x/bff/account/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: "k", scopes: ["a"] }),
        headers: { "Content-Type": "application/json" }
      })
    );
    expect(res.status).toBe(201);
    expect(JSON.parse(calls[1][1].body as string)).toEqual({ name: "k", scopes: ["a"] });
  });

  it("answers a malformed body with the route's JSON detail, not a framework error", async () => {
    const { POST } = await import("./api-keys/route");
    const { NextRequest } = await import("next/server");
    const res = await POST(
      new NextRequest("http://x/bff/account/api-keys", { method: "POST", body: "{oops" })
    );
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ detail: "Failed to create API key" });
  });
});
