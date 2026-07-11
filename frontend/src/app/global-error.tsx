"use client";

import { useEffect } from "react";

/**
 * Last-resort error boundary for failures in the root layout itself. It
 * replaces the entire document (must render <html>/<body>) and runs without
 * the app's providers, fonts, or stylesheet — so all styling is inline, using
 * the dark "Editorial Tactical" palette literally.
 */
export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "hsl(222 30% 6%)",
          color: "hsl(210 20% 95%)",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          padding: 24
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 480 }}>
          <div
            aria-hidden="true"
            style={{
              margin: "0 auto 20px",
              width: 48,
              height: 48,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 16,
              border: "1px solid hsl(0 72% 51% / 0.3)",
              background: "hsl(0 72% 51% / 0.12)",
              color: "hsl(0 72% 60%)",
              fontSize: 26,
              fontWeight: 700
            }}
          >
            !
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: "0 0 8px" }}>Something went wrong</h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "hsl(215 12% 60%)", margin: "0 0 24px" }}>
            The application failed to load. Please try again.
          </p>
          {error?.digest ? (
            <p
              style={{
                fontFamily: "ui-monospace, monospace",
                fontSize: 11,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: "hsl(215 12% 45%)",
                margin: "0 0 24px"
              }}
            >
              Error {error.digest}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => reset()}
            style={{
              cursor: "pointer",
              border: "none",
              borderRadius: 8,
              padding: "10px 18px",
              fontSize: 14,
              fontWeight: 600,
              background: "hsl(172 70% 49%)",
              color: "hsl(180 20% 8%)"
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
