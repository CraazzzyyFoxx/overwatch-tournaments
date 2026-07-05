"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./docs.module.css";

type MermaidApi = (typeof import("mermaid"))["default"];

// mermaid is heavy: import it once, lazily, only in the browser. The module is
// cached by the bundler, so the singleton (and its `initialize`) persists across
// every diagram render on the page.
let mermaidPromise: Promise<MermaidApi> | null = null;
let initialized = false;

async function getMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => mod.default);
  }
  const mermaid = await mermaidPromise;
  if (!initialized) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      securityLevel: "loose",
      fontFamily: "ui-monospace, 'JetBrains Mono', Consolas, monospace",
      themeVariables: {
        darkMode: true,
        background: "#0d1117",
        mainBkg: "#161b22",
        primaryColor: "#161b22",
        primaryBorderColor: "#2dd4bf",
        primaryTextColor: "#e6edf3",
        secondaryColor: "#12171f",
        tertiaryColor: "#0d1117",
        lineColor: "#2dd4bf",
        textColor: "#e6edf3",
        // ER attribute rows
        attributeBackgroundColorOdd: "#12171f",
        attributeBackgroundColorEven: "#0d1117",
        // Flowchart clusters (domain map)
        clusterBkg: "#12171f",
        clusterBorder: "#2b3440",
        nodeBorder: "#2dd4bf",
        edgeLabelBackground: "#0d1117"
      },
      er: {
        useMaxWidth: false,
        entityPadding: 15,
        layoutDirection: "TB"
      },
      flowchart: {
        useMaxWidth: false,
        htmlLabels: true,
        curve: "basis"
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
  /** Stable key for the active diagram (used to build a unique render id). */
  diagramKey: string;
  /**
   * `false` (default): fills the flex stage (absolute scroll region).
   * `true`: grows to content height inside a normal-flow block.
   */
  inline?: boolean;
}

export function MermaidDiagram({ code, diagramKey, inline = false }: MermaidDiagramProps) {
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
        const { svg, bindFunctions } = await mermaid.render(renderId, code);
        if (cancelled) return;
        const el = containerRef.current;
        if (el) {
          el.innerHTML = svg;
          bindFunctions?.(el);
        }
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Не удалось отрендерить диаграмму");
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, diagramKey]);

  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, Math.round((z + ZOOM_STEP) * 100) / 100));
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, Math.round((z - ZOOM_STEP) * 100) / 100));
  const zoomReset = () => setZoom(1);

  return (
    <div className={inline ? styles.diagramWrapInline : styles.diagramWrap}>
      <div className={styles.zoomControls}>
        <button
          type="button"
          className={styles.zoomBtn}
          onClick={zoomOut}
          aria-label="Уменьшить"
          disabled={zoom <= ZOOM_MIN}
        >
          −
        </button>
        <span className={styles.zoomLevel}>{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className={styles.zoomBtn}
          onClick={zoomIn}
          aria-label="Увеличить"
          disabled={zoom >= ZOOM_MAX}
        >
          +
        </button>
        <button type="button" className={styles.zoomBtn} onClick={zoomReset} aria-label="Сбросить">
          ⟲
        </button>
      </div>

      <div className={inline ? styles.diagramScrollInline : styles.diagramScroll}>
        <div
          ref={containerRef}
          className={styles.diagramInner}
          style={{ transform: `scale(${zoom})` }}
        />
      </div>

      {loading && !error && <div className={styles.diagramState}>Рендер диаграммы…</div>}
      {error && <div className={styles.diagramError}>Ошибка Mermaid: {error}</div>}
    </div>
  );
}
