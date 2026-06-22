import { describe, expect, it } from "bun:test";

import {
  decodeJwtPayload,
  getTokenExpMs,
  getTokenMaxAgeSeconds,
  isExpiredOrNearExpiry,
} from "@/lib/jwt";

// Builds an unsigned-looking JWT (header.payload.signature) carrying the given
// payload, base64url-encoded — enough for the payload-only decoder under test.
function makeToken(payload: Record<string, unknown>): string {
  const base64url = (obj: Record<string, unknown>) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${base64url({ alg: "HS256", typ: "JWT" })}.${base64url(payload)}.signature`;
}

describe("decodeJwtPayload", () => {
  it("decodes a valid payload", () => {
    expect(decodeJwtPayload(makeToken({ sub: "42", exp: 123 }))).toEqual({ sub: "42", exp: 123 });
  });

  it("returns undefined for malformed tokens", () => {
    expect(decodeJwtPayload("not-a-jwt")).toBeUndefined();
    expect(decodeJwtPayload("")).toBeUndefined();
  });
});

describe("getTokenExpMs", () => {
  it("returns exp in milliseconds", () => {
    expect(getTokenExpMs(makeToken({ exp: 1_000 }))).toBe(1_000_000);
  });

  it("returns undefined when exp is missing or non-numeric", () => {
    expect(getTokenExpMs(makeToken({ sub: "x" }))).toBeUndefined();
    expect(getTokenExpMs(makeToken({ exp: "soon" }))).toBeUndefined();
  });
});

describe("isExpiredOrNearExpiry", () => {
  const nowSec = () => Math.floor(Date.now() / 1000);

  it("is true for a missing token", () => {
    expect(isExpiredOrNearExpiry(undefined)).toBe(true);
  });

  it("is true for an expired token", () => {
    expect(isExpiredOrNearExpiry(makeToken({ exp: nowSec() - 10 }))).toBe(true);
  });

  it("is true within the skew window", () => {
    expect(isExpiredOrNearExpiry(makeToken({ exp: nowSec() + 30 }), 60_000)).toBe(true);
  });

  it("is false for a token comfortably in the future", () => {
    expect(isExpiredOrNearExpiry(makeToken({ exp: nowSec() + 3600 }), 60_000)).toBe(false);
  });

  it("is false when exp can't be decoded (defer to reactive path)", () => {
    expect(isExpiredOrNearExpiry(makeToken({ sub: "x" }))).toBe(false);
  });
});

describe("getTokenMaxAgeSeconds", () => {
  it("derives remaining lifetime from exp", () => {
    const maxAge = getTokenMaxAgeSeconds(makeToken({ exp: Math.floor(Date.now() / 1000) + 1000 }), 99);
    expect(maxAge).toBeGreaterThan(900);
    expect(maxAge).toBeLessThanOrEqual(1000);
  });

  it("clamps expired tokens to 0", () => {
    expect(getTokenMaxAgeSeconds(makeToken({ exp: Math.floor(Date.now() / 1000) - 100 }), 99)).toBe(0);
  });

  it("falls back when exp can't be decoded", () => {
    expect(getTokenMaxAgeSeconds(makeToken({ sub: "x" }), 99)).toBe(99);
  });
});
