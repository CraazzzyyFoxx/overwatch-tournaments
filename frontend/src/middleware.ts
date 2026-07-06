import { NextRequest, NextResponse } from "next/server";
import { PLATFORM_ZONE, resolveHost } from "@/lib/host";

// Small in-memory TTL cache: the host->workspace map is tiny and rarely changes.
const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { id: number | null; at: number }>();

async function resolveWorkspaceId(origin: string, subdomain: string): Promise<number | null> {
  const host = `${subdomain}.${PLATFORM_ZONE}`;
  const cached = cache.get(host);
  const now = Date.now();
  if (cached && now - cached.at < CACHE_TTL_MS) return cached.id;
  try {
    const res = await fetch(`${origin}/api/v1/workspaces/by-host?host=${encodeURIComponent(host)}`, {
      headers: { accept: "application/json" },
    });
    const data = res.ok ? await res.json() : null;
    const id = data?.workspace_id ?? null;
    cache.set(host, { id, at: now });
    return id;
  } catch {
    // A fetch failure (network blip, gateway restart) must never take the whole
    // site down. Degrade to "unknown" rather than caching or throwing — the next
    // request gets a fresh attempt instead of being stuck on a bad cache entry.
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const resolution = resolveHost(host);

  if (resolution.mode === "platform") {
    return NextResponse.next();
  }

  const workspaceId = await resolveWorkspaceId(request.nextUrl.origin, resolution.subdomain);
  if (workspaceId === null) {
    return NextResponse.rewrite(new URL("/not-configured", request.url), { status: 404 });
  }

  const headers = new Headers(request.headers);
  headers.set("x-owt-workspace-id", String(workspaceId));
  headers.set("x-owt-host-mode", "tenant");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  // Skip static assets + Next internals; run on pages + API-relative routes.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|webp|svg|ico)).*)"],
};
