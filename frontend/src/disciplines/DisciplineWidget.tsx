"use client";

import {
  createElement,
  Suspense,
  useEffect,
  useState,
  useSyncExternalStore,
  type ComponentType,
  type ReactNode
} from "react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";

import type { DisciplineLoader } from "./registry/create";
import type { DisciplineCapabilities, DisciplineSlot, DisciplineUI, SlotProps } from "./types";

interface DisciplineWidgetProps<F extends DisciplineSlot, K extends F> {
  discipline: string;
  /** The loader of the slot's family (`loadRankUI`, `loadPregameUI`, `loadAdminUI`): the host reaches only that family's modules. */
  load: DisciplineLoader<F>;
  slot: K;
  capabilities: DisciplineCapabilities;
  /** The native capability this slot needs; a promised-but-unimplemented one is a configuration error. */
  requires?: keyof DisciplineCapabilities;
  /** Native shape check (e.g. exactly two participants); `false` renders `fallback`. */
  applicable?: boolean;
  props: SlotProps[K];
  /** Working generic view (facts table etc.). */
  fallback: ReactNode;
  /** Shown while the family's module (and its lazy slot) loads; nothing by default. Never the generic fallback. */
  pending?: ReactNode;
}

/** `failed`: the game has a module for this family but its chunk did not load — retryable, not "no module". */
type Loaded = { code: string; ui: DisciplineUI | null; failed: boolean };

// Nothing to subscribe to: a load settles through the widget's own effect.
const subscribeNone = () => () => {};

/**
 * Renders one optional module slot (P7 contracts §7). Backend capability and local renderer are separate
 * facts: a capability without its renderer is an explicit configuration error, an unsupported capability is
 * said so, a module that failed to load is a retryable error, and everything else falls back to the generic
 * view. An unknown discipline never resolves to another game's module.
 */
export function DisciplineWidget<F extends DisciplineSlot, K extends F>({
  discipline,
  load,
  slot,
  capabilities,
  requires,
  applicable = true,
  props,
  fallback,
  pending = null
}: Readonly<DisciplineWidgetProps<F, K>>): ReactNode {
  const t = useTranslations("common");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // An already-settled module renders on the first commit: a host mounted on demand (a hover card) would otherwise
  // paint empty, then resize once the effect's promise answered — on every open. Hydration still starts from the
  // server's view (never settled): another widget on the page may settle the module before this boundary hydrates.
  const settled = useSyncExternalStore(subscribeNone, () => load.peek(discipline), () => undefined);
  const current: Loaded | null = settled === undefined ? loaded : { code: discipline, ui: settled, failed: false };
  const [attempt, setAttempt] = useState(0);
  const blocked = (requires !== undefined && !capabilities[requires]) || !applicable;

  useEffect(() => {
    if (blocked || load.peek(discipline) !== undefined) return;
    let live = true;
    void load(discipline).then(
      (ui) => {
        if (live) setLoaded({ code: discipline, ui, failed: false });
      },
      () => {
        if (live) setLoaded({ code: discipline, ui: null, failed: true });
      }
    );
    return () => {
      live = false;
    };
  }, [discipline, load, blocked, attempt]);

  if (requires !== undefined && !capabilities[requires]) {
    return <p className="text-sm text-muted-foreground">{t("discipline.widgetUnsupported")}</p>;
  }
  if (!applicable) return fallback;

  // Still resolving the family's module: the caller's neutral `pending` view, never its fallback — the fallback says
  // "this game has no renderer", which is only known once the loader has answered.
  if (current?.code !== discipline) return pending;
  if (current.failed) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
        <span>{t("discipline.widgetLoadFailed")}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            setLoaded(null);
            setAttempt((n) => n + 1);
          }}
        >
          {t("retry")}
        </Button>
      </div>
    );
  }
  const Slot = current.ui?.slots[slot] as ComponentType<SlotProps[K]> | undefined;
  if (!Slot) {
    return requires === undefined ? (
      fallback
    ) : (
      <p role="alert" className="text-sm text-destructive">
        {t("discipline.widgetMissing")}
      </p>
    );
  }
  return <Suspense fallback={pending}>{createElement(Slot, props)}</Suspense>;
}
