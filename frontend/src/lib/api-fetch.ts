import { cache } from "react";
import { getTokenFromCookies } from "./auth-tokens";
import { retryWithRefreshOnUnauthorized } from "./auth-request";
import { parseApiError } from "./api-error";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { internalApiOrigin } from "./api-routes";

// Default timeout (ms) for server-side (SSR) fetches. A hung or looping upstream
// must not block a render indefinitely or pile up requests that exhaust the Node
// process; client fetches stay untimed unless a caller passes options.timeout.
const DEFAULT_SERVER_TIMEOUT_MS = 15_000;

// ─── Types ──────────────────────────────────────────────────────────────────

interface ApiFetchOptions {
  query?: Record<string, unknown>;
  body?: unknown;
  method?: string;
  token?: string;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  cache?: RequestCache;
  /**
   * Next.js Data Cache options. Set `revalidate` (seconds) to cache a public,
   * server-side GET in the Data Cache (works even after cookies() are read);
   * `tags` enable on-demand `revalidateTag`. Ignored by the browser on client
   * fetches. Only use for responses that depend solely on the URL (public data).
   */
  next?: { revalidate?: number | false; tags?: string[] };
  timeout?: number;
  skipWorkspace?: boolean;
  throwOnError?: boolean;
}

// ─── Per-domain behaviour (keyed by path prefix) ──────────────────────────────
//
// The gateway is a single origin, so the path's top-level namespace IS the
// domain. Behaviour (workspace injection + default cache) is attached per
// domain, not per service. Callers pass the full gateway path, e.g.
//   apiFetch("/api/v1/tournaments/5")
//   apiFetch("/api/balancer/config")
//   apiFetch("/api/auth/me")

const cachePolicy = process.env.NEXT_PUBLIC_CACHE_POLICY;

function resolveV1Cache(): RequestCache {
  switch (cachePolicy) {
    case "no-cache":
      return "no-cache";
    case "network-only":
      return "no-store";
    default:
      return "default";
  }
}

interface DomainBehavior {
  injectWorkspace: boolean;
  defaultCache: RequestCache;
}

function domainBehavior(path: string): DomainBehavior {
  // Identity domain: no workspace scoping.
  if (path.startsWith("/api/auth")) {
    return { injectWorkspace: false, defaultCache: "no-store" };
  }
  // Main API (app + tournament + parser): workspace-scoped, cache per policy.
  if (path.startsWith("/api/v1")) {
    return { injectWorkspace: true, defaultCache: resolveV1Cache() };
  }
  // /api/balancer, /api/analytics, and any other workspace-scoped domain.
  return { injectWorkspace: true, defaultCache: "no-store" };
}

// ─── Workspace ID (server-side, cached per request) ─────────────────────────

const getServerWorkspaceId = cache(async (): Promise<string | undefined> => {
  try {
    const { headers, cookies } = await import("next/headers");
    const headerId = (await headers()).get("x-owt-workspace-id");
    if (headerId) return headerId;
    const cookieStore = await cookies();
    return cookieStore.get("owt-workspace-id")?.value ?? cookieStore.get("aqt-workspace-id")?.value;
  } catch {
    return undefined;
  }
});

const getServerRequestOrigin = cache(async (): Promise<string | undefined> => {
  const configuredOrigin = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "");

  try {
    const { headers } = await import("next/headers");
    const headersList = await headers();
    const forwardedHost = headersList.get("x-forwarded-host") ?? headersList.get("host");
    const host = forwardedHost?.split(",")[0]?.trim();

    if (!host) {
      return configuredOrigin;
    }

    const forwardedProto = headersList.get("x-forwarded-proto")?.split(",")[0]?.trim();
    const protocol =
      forwardedProto ||
      (host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https");

    return `${protocol}://${host}`;
  } catch {
    return configuredOrigin;
  }
});

// ─── Query Param Serialization ──────────────────────────────────────────────

function appendParams(params: URLSearchParams, key: string, value: unknown): void {
  if (value === undefined || value === null) return;

  if (Array.isArray(value)) {
    for (const item of value) {
      params.append(key, String(item));
    }
  } else if (typeof value === "object") {
    for (const subKey in value as Record<string, unknown>) {
      appendParams(params, key, (value as Record<string, unknown>)[subKey]);
    }
  } else {
    params.append(key, String(value));
  }
}

// resolveBaseUrl returns the origin to prepend to the (relative) gateway path.
// Client: "" (same-origin). Server: the internal gateway base, or the incoming
// request origin as a fallback when NEXT_INTERNAL_API_URL is unset.
async function resolveBaseUrl(): Promise<string> {
  if (typeof window !== "undefined") {
    return "";
  }

  const internal = internalApiOrigin();
  if (internal) {
    return internal;
  }

  const origin = await getServerRequestOrigin();
  if (!origin) {
    throw new Error(
      "Cannot resolve the API base URL on the server (set NEXT_INTERNAL_API_URL)",
    );
  }
  return origin;
}

// ─── Main Function ──────────────────────────────────────────────────────────

export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {},
): Promise<Response> {
  const behavior = domainBehavior(path);
  const throwOnError = options.throwOnError ?? true;

  // Extract inline query params from path (e.g. "/api/v1/users?page=1")
  let cleanPath = path;
  const params = new URLSearchParams();
  const qIndex = path.indexOf("?");
  if (qIndex !== -1) {
    cleanPath = path.slice(0, qIndex);
    const inline = new URLSearchParams(path.slice(qIndex + 1));
    inline.forEach((v, k) => params.append(k, v));
  }
  if (!cleanPath.startsWith("/")) {
    cleanPath = `/${cleanPath}`;
  }

  // Auto-inject workspace_id
  if (
    behavior.injectWorkspace &&
    !options.skipWorkspace &&
    !options.query?.workspace_id &&
    !params.has("workspace_id")
  ) {
    const workspaceId =
      typeof window !== "undefined"
        ? useWorkspaceStore.getState().currentWorkspaceId
        : await getServerWorkspaceId();

    if (workspaceId != null) {
      params.append("workspace_id", String(workspaceId));
    }
  }

  // Serialize query options
  if (options.query) {
    for (const key in options.query) {
      appendParams(params, key, options.query[key]);
    }
  }

  // Build URL
  const baseUrl = await resolveBaseUrl();
  const qs = params.toString();
  const url = qs ? `${baseUrl}${cleanPath}?${qs}` : `${baseUrl}${cleanPath}`;

  // Auth token
  const initialToken = options.token ?? (await getTokenFromCookies("aqt_access_token"));

  // Headers
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = { ...options.headers };
  if (!isFormData && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  // Timeout. Honor an explicit options.timeout; otherwise apply a default on the
  // server so a hung/slow/looping upstream can't block SSR indefinitely (and pile
  // up requests that exhaust the Node process). Client fetches keep prior behavior.
  let abortController: AbortController | undefined;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let signal = options.signal;

  const effectiveTimeout =
    options.timeout ?? (typeof window === "undefined" ? DEFAULT_SERVER_TIMEOUT_MS : undefined);
  if (effectiveTimeout && !signal) {
    abortController = new AbortController();
    signal = abortController.signal;
    timeoutId = setTimeout(() => abortController!.abort(), effectiveTimeout);
  }

  // Request runner (for auth retry)
  const runRequest = async (tokenToUse?: string): Promise<Response> => {
    const requestHeaders: Record<string, string> = { ...headers };
    if (tokenToUse) {
      requestHeaders.Authorization = `Bearer ${tokenToUse}`;
    }

    const init: RequestInit & { next?: { revalidate?: number | false; tags?: string[] } } = {
      headers: requestHeaders,
      body: isFormData ? (options.body as FormData) : options.body ? JSON.stringify(options.body) : undefined,
      method: options.method || "GET",
      signal,
    };
    if (options.next) {
      // An explicit revalidate enables the Data Cache even when the route is
      // dynamic (cookies read) and the request carries an Authorization header.
      init.next = options.next;
      if (options.cache) init.cache = options.cache;
    } else {
      init.cache = options.cache ?? behavior.defaultCache;
    }
    return fetch(url, init);
  };

  try {
    const response = await retryWithRefreshOnUnauthorized({
      response: await runRequest(initialToken),
      token: options.token,
      runRequest,
    });

    if (!response.ok && throwOnError) {
      throw await parseApiError(response);
    }

    return response;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}
