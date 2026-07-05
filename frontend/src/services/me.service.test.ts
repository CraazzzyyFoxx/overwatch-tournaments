import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture what me.service sends to apiFetch. The gateway avatar handler
// (POST /api/auth/me/avatar) requires a multipart form with a "file" field and
// rejects a JSON body with 400 — this guards that setAvatar posts FormData, not
// a base64 JSON payload (the historical bug where My Account avatar changes
// silently failed while the admin path, which already sent FormData, worked).
type Call = { path: string; options?: { method?: string; body?: unknown } };
const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (path: string, options?: { method?: string; body?: unknown }) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({}) });
  },
}));

const { default: meService } = await import("@/services/me.service");

describe("meService.setAvatar", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("uploads the avatar as multipart FormData with a 'file' field", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "avatar.png", { type: "image/png" });

    await meService.setAvatar(file);

    expect(calls[0].path).toBe("/api/auth/me/avatar");
    expect(calls[0].options?.method).toBe("POST");

    const body = calls[0].options?.body;
    expect(body).toBeInstanceOf(FormData);
    const sent = (body as FormData).get("file");
    expect(sent).toBeInstanceOf(File);
    expect((sent as File).name).toBe("avatar.png");
    expect((sent as File).type).toBe("image/png");
    expect((sent as File).size).toBe(3);
  });

  it("deletes the avatar via DELETE with no body", async () => {
    await meService.deleteAvatar();

    expect(calls[0].path).toBe("/api/auth/me/avatar");
    expect(calls[0].options?.method).toBe("DELETE");
    expect(calls[0].options?.body).toBeUndefined();
  });
});

describe("meService.unlinkOAuth", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("unlinks an OAuth provider via DELETE on the identity route", async () => {
    await meService.unlinkOAuth("discord");

    expect(calls[0].path).toBe("/api/auth/oauth/discord/unlink");
    expect(calls[0].options?.method).toBe("DELETE");
  });
});
