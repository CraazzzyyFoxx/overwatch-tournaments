"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { TONE_TEXT } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

type MermaidApi = (typeof import("mermaid"))["default"];

// mermaid is heavy: import it once, lazily, only in the browser. The module is
// cached by the bundler, so the singleton (and its `initialize`) persists across
// every diagram render on the page.
let mermaidPromise: Promise<MermaidApi> | null = null;
let initialized = false;

// Mermaid's theming is a JS API: it takes plain colour strings and runs its own
// colour maths over them, so it cannot read CSS custom properties — `var()` in
// `themeVariables` would not resolve. Rather than hardcode a second copy of the
// palette, resolve the --aqt-* tokens once at init and hand mermaid the computed
// values, so the diagrams follow the app theme. The hex fallbacks are the values
// this file used to carry, for when the tokens are unreachable (no DOM).
const THEME_FALLBACK = {
  "--aqt-bg": "#0d1117",
  "--aqt-card": "#12171f",
  "--aqt-card-2": "#161b22",
  "--aqt-fg": "#e6edf3",
  "--aqt-teal": "#2dd4bf"
};
// Same stack as Tailwind's `font-mono`: diagrams are code-adjacent, not UI labels.
const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

/** Reads the palette off `<body>`, where the `:root` `--aqt-*` tokens have inherited down. */
function readTheme(): { c: Record<string, string>; mono: string } {
  const c: Record<string, string> = { ...THEME_FALLBACK };
  if (typeof document === "undefined" || typeof getComputedStyle !== "function" || !document.body) {
    return { c, mono: MONO };
  }
  const bodyStyle = getComputedStyle(document.body);
  const probe = document.createElement("div");
  probe.style.display = "none";
  document.body.appendChild(probe);
  try {
    for (const token of Object.keys(THEME_FALLBACK)) {
      const raw = bodyStyle.getPropertyValue(token).trim();
      if (!raw) continue;
      // Tokens are authored as `hsl(h s% l%)`, which mermaid's colour maths does
      // not parse. Round-trip through `color` so the browser returns `rgb(...)`.
      probe.style.color = "";
      probe.style.color = raw;
      if (!probe.style.color) continue;
      const normalised = getComputedStyle(probe).color;
      if (normalised) c[token] = normalised;
    }
    return { c, mono: MONO };
  } finally {
    probe.remove();
  }
}

async function getMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => mod.default);
  }
  const mermaid = await mermaidPromise;
  if (!initialized) {
    const { c, mono } = readTheme();
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      securityLevel: "strict",
      fontFamily: mono,
      themeVariables: {
        darkMode: true,
        background: c["--aqt-bg"],
        mainBkg: c["--aqt-card-2"],
        primaryColor: c["--aqt-card-2"],
        primaryBorderColor: c["--aqt-teal"],
        primaryTextColor: c["--aqt-fg"],
        secondaryColor: c["--aqt-card"],
        tertiaryColor: c["--aqt-bg"],
        lineColor: c["--aqt-teal"],
        textColor: c["--aqt-fg"],
        // ER attribute rows
        attributeBackgroundColorOdd: c["--aqt-card"],
        attributeBackgroundColorEven: c["--aqt-bg"],
        edgeLabelBackground: c["--aqt-bg"]
      },
      er: {
        useMaxWidth: false,
        entityPadding: 15,
        layoutDirection: "TB"
      }
    });
    initialized = true;
  }
  return mermaid;
}

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 0.15;

interface MermaidDiagramProps {
  /** Verbatim Mermaid source. */
  code: string;
  /** Stable key for the diagram (used to build a unique render id). */
  diagramKey: string;
}

export function MermaidDiagram({ code, diagramKey }: Readonly<MermaidDiagramProps>) {
  const t = useTranslations("docs.schema");
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);

  // No synchronous state reset here: callers pass a `key` so switching diagrams
  // remounts the component with fresh initial state (loading=true, zoom=1). The
  // setState calls below all run after an `await`, so they never cascade the
  // initial render synchronously.
  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const mermaid = await getMermaid();
        // Unique id per render — mermaid errors if an id is reused.
        const renderId = `mermaid-${diagramKey}-${Math.random().toString(36).slice(2, 9)}`;
        const { svg } = await mermaid.render(renderId, code);
        if (cancelled) return;
        if (containerRef.current) containerRef.current.innerHTML = svg;
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, diagramKey]);

  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, Math.round((z + ZOOM_STEP) * 100) / 100));
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, Math.round((z - ZOOM_STEP) * 100) / 100));

  return (
    <div className="relative mt-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
      <div className="absolute right-2 top-2 z-5 flex gap-1 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-1">
        <Button
          variant="outline"
          size="icon-sm"
          onClick={zoomOut}
          aria-label={t("zoomOut")}
          disabled={zoom <= ZOOM_MIN}
        >
          −
        </Button>
        <span className="aqt-tnum inline-flex min-w-11 items-center justify-center px-1.5 text-label text-[color:var(--aqt-fg-muted)]">
          {Math.round(zoom * 100)}%
        </span>
        <Button
          variant="outline"
          size="icon-sm"
          onClick={zoomIn}
          aria-label={t("zoomIn")}
          disabled={zoom >= ZOOM_MAX}
        >
          +
        </Button>
        <Button variant="outline" size="icon-sm" onClick={() => setZoom(1)} aria-label={t("zoomReset")}>
          1:1
        </Button>
      </div>

      <div className="max-h-[75vh] min-h-35 overflow-auto px-4 pb-4 pt-12">
        {/* Mermaid writes an inline `max-width` on its svg; zoom needs the natural size. */}
        <div
          ref={containerRef}
          className="w-max origin-top-left transition-transform duration-80 ease-out [&_svg]:h-auto [&_svg]:max-w-none!"
          style={{ transform: `scale(${zoom})` }}
        />
      </div>

      {loading && !error && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-caption text-[color:var(--aqt-fg-muted)]">
          {t("rendering")}
        </div>
      )}
      {error && (
        <div className={cn("whitespace-pre-wrap p-4 text-caption", TONE_TEXT.danger)}>
          {t("renderError", { message: error })}
        </div>
      )}
    </div>
  );
}
