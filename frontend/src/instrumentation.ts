/**
 * Next.js instrumentation hook (runs once when the server process starts).
 *
 * `register()` is compiled for every runtime (Node.js and Edge), so anything
 * touching `process.*` must be isolated behind a NEXT_RUNTIME guard *and* a
 * dynamic import — a top-level `process.on` here would be statically bundled
 * into the Edge build and rejected by Turbopack. The actual Node-only setup
 * (an unhandledRejection guard that keeps the server alive) lives in
 * ./instrumentation.node.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./instrumentation.node");
  }
}
