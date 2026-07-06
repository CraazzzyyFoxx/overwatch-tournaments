import { NextRequest, NextResponse } from "next/server";
import { PLATFORM_ZONE, resolveHost } from "@/lib/host";

// Small bounded TTL cache: the host->workspace map is tiny and rarely changes.
const CACHE_TTL_MS = 60_000;
const CACHE_MAX = 1000;
const cache = new Map<string, { id: number | null; at: number }>();

function setCache(host: string, id: number | null, at: number): void {
  // Rough FIFO eviction: Map preserves insertion order, so the first key is oldest.
  if (cache.size >= CACHE_MAX) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(host, { id, at });
}

type Lookup = { status: "found"; id: number } | { status: "not_found" } | { status: "error" };

function fromEntry(entry: { id: number | null }): Lookup {
  return entry.id === null ? { status: "not_found" } : { status: "found", id: entry.id };
}

async function resolveWorkspace(origin: string, subdomain: string): Promise<Lookup> {
  const host = `${subdomain}.${PLATFORM_ZONE}`;
  const now = Date.now();
  const cached = cache.get(host);
  if (cached && now - cached.at < CACHE_TTL_MS) {
    return fromEntry(cached);
  }
  try {
    const res = await fetch(`${origin}/api/v1/workspaces/by-host?host=${encodeURIComponent(host)}`, {
      headers: { accept: "application/json" },
    });
    if (!res.ok) {
      // Transient backend failure: never cache it. Serve stale if we have it, else surface a 503.
      return cached ? fromEntry(cached) : { status: "error" };
    }
    const data = await res.json();
    const id = typeof data?.workspace_id === "number" ? data.workspace_id : null;
    setCache(host, id, now);
    return id === null ? { status: "not_found" } : { status: "found", id };
  } catch {
    return cached ? fromEntry(cached) : { status: "error" };
  }
}

export async function middleware(request: NextRequest) {
  const rawHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const host = rawHost?.split(",")[0]?.trim() ?? null;
  const resolution = resolveHost(host);

  if (resolution.mode === "platform") {
    return NextResponse.next();
  }

  const lookup = await resolveWorkspace(request.nextUrl.origin, resolution.subdomain);

  if (lookup.status === "found") {
    const headers = new Headers(request.headers);
    headers.set("x-owt-workspace-id", String(lookup.id));
    headers.set("x-owt-host-mode", "tenant");
    return NextResponse.next({ request: { headers } });
  }

  if (lookup.status === "not_found") {
    return NextResponse.rewrite(new URL("/not-configured", request.url), { status: 404 });
  }

  // Transient lookup failure — do not 404 a real tenant.
  return new NextResponse("Service temporarily unavailable", {
    status: 503,
    headers: { "retry-after": "5" },
  });
}

export const config = {
  // Skip API route handlers, Next internals, and static assets.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|webp|svg|ico)).*)"],
};
