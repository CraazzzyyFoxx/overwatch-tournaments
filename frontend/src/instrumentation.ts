/**
 * Next.js instrumentation hook (runs once when the server process starts).
 *
 * A failed or aborted server-side fetch (slow/unreachable/looping upstream)
 * surfaces as a promise rejection. Errors thrown *inside* a render are caught by
 * Next.js error boundaries, but a stray rejection from a detached promise would
 * otherwise be treated as fatal by Node (>=15) and crash the whole server,
 * taking the entire site down and triggering a restart loop. Log it and keep
 * serving instead — a single bad upstream request must not be fatal.
 */
export function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  process.on("unhandledRejection", (reason) => {
    console.error("[instrumentation] unhandledRejection:", reason);
  });
}
