import { type APIRequestContext, type APIResponse, expect, request as pwRequest } from "@playwright/test";
import { setTimeout as sleep } from "node:timers/promises";
import { BASE_URL } from "./env";

type Body = Record<string, unknown> | unknown[] | undefined;
type Query = Record<string, string | number | boolean | undefined>;

type Nodes = { registration?: number; formation?: number };
const nodesOfTournament = new Map<number, Nodes>();
// shortcut: per-registration admin routes carry no tournament id, so they take the last remembered intake; a spec
// interleaving two tournaments' per-registration calls must pass `registration_node_id` itself.
let lastRegistrationNode: number | undefined;

/**
 * Records the registration/formation node a helper opened or looked up (`nodeOf`, `openRegistration`). Participation and
 * balancer routes take the node as a required query parameter (`?registration_node_id=`, `?formation_node_id=`); the specs
 * address the one node they made, so `Api.raw` adds it for them instead of every URL spelling it.
 */
export function rememberNodes(tournamentId: number, nodes: Nodes) {
  nodesOfTournament.set(tournamentId, { ...nodesOfTournament.get(tournamentId), ...nodes });
  if (nodes.registration !== undefined) lastRegistrationNode = nodes.registration;
}

const REGISTRATION_ROUTE = /\/tournaments\/(\d+)\/(registration(\/(me|list)|$)|registration-teams)|\/admin\/balancer\/tournaments\/(\d+)\/registrations/;
const REGISTRATION_ENTRY_ROUTE = /\/admin\/balancer\/registrations\/\d+/;
const FORMATION_ROUTE = /\/balancer\/(?:draft\/)?tournaments\/(\d+)\/(balance|config|teams\/import|registered-teams\/export|sessions|draft)/;

function nodeQuery(url: string): Query {
  const path = url.split("?")[0];
  const registration = REGISTRATION_ROUTE.exec(path);
  if (registration) {
    const node = nodesOfTournament.get(Number(registration[1] ?? registration[5]))?.registration;
    return node === undefined ? {} : { registration_node_id: node };
  }
  if (REGISTRATION_ENTRY_ROUTE.test(path)) return lastRegistrationNode === undefined ? {} : { registration_node_id: lastRegistrationNode };
  const formation = FORMATION_ROUTE.exec(path);
  const node = formation ? nodesOfTournament.get(Number(formation[1]))?.formation : undefined;
  return node === undefined ? {} : { formation_node_id: node };
}

/**
 * Thin bearer-token client over the gateway. Every call asserts a 2xx unless
 * `expectStatus` names another code, and failures print the response body:
 * a regression shows up as "POST /x -> 422 {detail…}", not as a bare timeout.
 */
export class Api {
  constructor(
    readonly ctx: APIRequestContext,
    readonly token?: string
  ) {}

  static async create(token?: string): Promise<Api> {
    return new Api(await pwRequest.newContext({ baseURL: BASE_URL }), token);
  }

  async raw(method: string, url: string, opts: { body?: Body; query?: Query; headers?: Record<string, string> } = {}) {
    const headers: Record<string, string> = { accept: "application/json", ...opts.headers };
    if (this.token) headers.authorization = `Bearer ${this.token}`;
    const merged = { ...nodeQuery(url), ...opts.query };
    const params = Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== undefined)) as Record<string, string | number | boolean>;
    return this.ctx.fetch(url, { method, headers, data: opts.body, params });
  }

  async call<T = any>(
    method: string,
    url: string,
    opts: { body?: Body; query?: Query; expectStatus?: number } = {}
  ): Promise<T> {
    const res = await this.raw(method, url, opts);
    await assertStatus(res, method, url, opts.expectStatus);
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  get<T = any>(url: string, query?: Query) {
    return this.call<T>("GET", url, { query });
  }
  post<T = any>(url: string, body?: Body, expectStatus?: number) {
    return this.call<T>("POST", url, { body, expectStatus });
  }
  put<T = any>(url: string, body?: Body) {
    return this.call<T>("PUT", url, { body });
  }
  patch<T = any>(url: string, body?: Body) {
    return this.call<T>("PATCH", url, { body });
  }
  delete<T = any>(url: string, expectStatus?: number) {
    return this.call<T>("DELETE", url, { expectStatus });
  }

  async dispose() {
    await this.ctx.dispose();
  }
}

export async function assertStatus(res: APIResponse, method: string, url: string, expected?: number) {
  const ok = expected === undefined ? res.ok() : res.status() === expected;
  if (!ok) {
    const body = (await res.text()).slice(0, 2000);
    expect(ok, `${method} ${url} -> ${res.status()} ${body}`).toBe(true);
  }
}

/** Polls `fn` until it returns a truthy value (async jobs: balance, generate, recalculation). */
export async function poll<T>(fn: () => Promise<T | undefined | null | false>, what: string, timeoutMs = 30_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: unknown;
  while (Date.now() < deadline) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (error) {
      last = error;
    }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for ${what}${last ? `: ${String(last)}` : ""}`);
}
