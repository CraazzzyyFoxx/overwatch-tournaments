/**
 * Node.js-only instrumentation. Imported lazily from `register()` in
 * instrumentation.ts, guarded by NEXT_RUNTIME === "nodejs", so `process.on`
 * is never pulled into the Edge Runtime bundle (Turbopack would otherwise
 * statically flag it as an unsupported Edge API).
 *
 * A failed or aborted server-side fetch (slow/unreachable/looping upstream)
 * surfaces as a promise rejection. Errors thrown *inside* a render are caught by
 * Next.js error boundaries, but a stray rejection from a detached promise would
 * otherwise be treated as fatal by Node (>=15) and crash the whole server,
 * taking the entire site down and triggering a restart loop. Log it and keep
 * serving instead — a single bad upstream request must not be fatal.
 *
 * `export {}` marks this as a module (no top-level import/export otherwise), so
 * the `await import("./instrumentation.node")` in instrumentation.ts type-checks.
 */
export {};

process.on("unhandledRejection", (reason) => {
  console.error("[instrumentation] unhandledRejection:", reason);
});
