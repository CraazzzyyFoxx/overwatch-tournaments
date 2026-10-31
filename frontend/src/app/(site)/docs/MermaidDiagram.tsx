"use client";

import { useTranslations } from "next-intl";
import { Maximize2 } from "lucide-react";
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

const ZOOM_MIN = 0.1;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 1.2;
// Initial offset clears the floating toolbar.
const ORIGIN = { x: 16, y: 48 };

interface View {
  x: number;
  y: number;
  k: number;
}

/** Rescales `view` to `k`, keeping the viewport point (px, py) fixed under the cursor. */
function zoomAt(view: View, k: number, px: number, py: number): View {
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, k));
  const r = next / view.k;
  return { k: next, x: px - (px - view.x) * r, y: py - (py - view.y) * r };
}

interface MermaidDiagramProps {
  /** Verbatim Mermaid source. */
  code: string;
  /** Stable key for the diagram (used to build a unique render id). */
  diagramKey: string;
}

export function MermaidDiagram({ code, diagramKey }: Readonly<MermaidDiagramProps>) {
  const t = useTranslations("docs.schema");
  const viewportRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: number; x: number; y: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [contentHeight, setContentHeight] = useState<number | null>(null);
  const [view, setView] = useState<View>({ ...ORIGIN, k: 1 });

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
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
          setContentHeight(containerRef.current.offsetHeight);
        }
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

  // React's onWheel is passive, so preventDefault (stop the page scrolling) needs a native listener.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      setView((v) => zoomAt(v, v.k * Math.exp(-e.deltaY * 0.0015), px, py));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoomCentered = (factor: number) => {
    const el = viewportRef.current;
    if (!el) return;
    setView((v) => zoomAt(v, v.k * factor, el.clientWidth / 2, el.clientHeight / 2));
  };

  const fit = () => {
    const vp = viewportRef.current;
    const content = containerRef.current;
    if (!vp || !content) return;
    const w = content.offsetWidth;
    const h = content.offsetHeight;
    const fitK = Math.min(1, (vp.clientWidth - 32) / w, (vp.clientHeight - ORIGIN.y - 16) / h);
    const k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, fitK));
    setView({ k, x: (vp.clientWidth - w * k) / 2, y: ORIGIN.y + (vp.clientHeight - ORIGIN.y - h * k) / 2 });
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== e.pointerId) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    dragRef.current = { ...drag, x: e.clientX, y: e.clientY };
    setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  };
  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.id === e.pointerId) dragRef.current = null;
  };

  const zoom = view.k;

  return (
    <div className="relative mt-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
      <div className="absolute right-2 top-2 z-5 flex gap-1 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-1">
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => zoomCentered(1 / ZOOM_STEP)}
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
          onClick={() => zoomCentered(ZOOM_STEP)}
          aria-label={t("zoomIn")}
          disabled={zoom >= ZOOM_MAX}
        >
          +
        </Button>
        <Button variant="outline" size="icon-sm" onClick={fit} aria-label={t("zoomFit")}>
          <Maximize2 className="size-3.5" />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => setView({ ...ORIGIN, k: 1 })}
          aria-label={t("zoomReset")}
        >
          1:1
        </Button>
      </div>

      {/* Wheel zooms at the cursor, drag pans. Height hugs small diagrams, caps big ones. */}
      <div
        ref={viewportRef}
        className="relative cursor-grab touch-none select-none overflow-hidden active:cursor-grabbing"
        style={{
          height: contentHeight === null ? "35vh" : `min(75vh, ${contentHeight + ORIGIN.y + 16}px)`,
          minHeight: 140
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {/* Mermaid writes an inline `max-width` on its svg; zoom needs the natural size. */}
        <div
          ref={containerRef}
          className="absolute left-0 top-0 w-max origin-top-left [&_svg]:h-auto [&_svg]:max-w-none!"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}
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
