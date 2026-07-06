import { handleOAuthCallback } from "@/lib/oauth-callback";

// Single fixed apex callback for every OAuth provider (one registered
// redirect_uri, per docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md).
// The provider is no longer known from a cookie or the URL — oauth-callback.ts
// decodes it from the signed `state` query param instead (Task 9 embeds it).
export async function GET(request: Request) {
  return handleOAuthCallback(request);
}
