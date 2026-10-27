"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type RefObject
} from "react";
import { useTranslations } from "next-intl";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";
import { holdScrollPosition } from "@/lib/scroll-hold";
import { useInSettingsPreview } from "./SettingsContinuation";

interface OutlineEntry {
  id: string;
  title: string;
  element: HTMLElement;
}

type Register = (entry: OutlineEntry) => () => void;

const RegisterContext = createContext<Register | null>(null);
const EntriesContext = createContext<readonly OutlineEntry[]>([]);

/** Below this many groups a page reads top to bottom; an outline is not a choice. */
const MIN_GROUPS = 3;
/**
 * A group is current once its top has passed this line: the admin top bar
 * (48px) plus the `scroll-mt-16` gap a jump leaves above the group, plus slack.
 */
const ACTIVATION_LINE_PX = 96;
const NO_ENTRIES: readonly OutlineEntry[] = [];

const byDocumentOrder = (a: OutlineEntry, b: OutlineEntry) =>
  a.element.compareDocumentPosition(b.element) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;

/**
 * Collects the `SettingGroup`s rendered under it, so the section rail can list
 * them as an outline of the page.
 *
 * Mounted by the T5 shells around both the rail and the page; a group outside
 * a provider still renders, it just is not listed anywhere.
 */
export function SettingsOutlineProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [entries, setEntries] = useState<OutlineEntry[]>([]);
  const register = useCallback<Register>((entry) => {
    setEntries((current) =>
      [...current.filter((item) => item.element !== entry.element), entry].sort(byDocumentOrder)
    );
    return () => setEntries((current) => current.filter((item) => item.element !== entry.element));
  }, []);

  return (
    <RegisterContext.Provider value={register}>
      <EntriesContext.Provider value={entries}>{children}</EntriesContext.Provider>
    </RegisterContext.Provider>
  );
}

/** Lists one group in the nearest outline; a no-op outside a provider or inside a preview. */
export function useSettingsOutlineEntry(
  id: string,
  title: string,
  ref: RefObject<HTMLElement | null>
) {
  const register = useContext(RegisterContext);
  const inPreview = useInSettingsPreview();
  useEffect(() => {
    const element = ref.current;
    if (!register || inPreview || !element) return;
    return register({ id, title, element });
  }, [register, inPreview, id, title, ref]);
}

/**
 * The group the reader is in: the last one whose top has passed the
 * activation line, or the last group outright once a scrolled page cannot go
 * any further (a short final group never reaches the line). A page that has
 * not scrolled is at its first group, even when it fits the window whole.
 *
 * A jump pins its target until the reader scrolls on their own, so the smooth
 * scroll does not sweep the highlight through every group it passes, and a
 * jump to a short group at the bottom keeps that group lit.
 */
function useActiveGroup(entries: readonly OutlineEntry[]) {
  const [active, setActive] = useState<string | null>(null);
  const pinned = useRef<string | null>(null);
  const jumping = useRef(false);

  useEffect(() => {
    if (entries.length === 0) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      if (pinned.current) return setActive(pinned.current);
      const root = document.documentElement;
      const scrolled = window.scrollY > 0;
      if (scrolled && window.innerHeight + window.scrollY >= root.scrollHeight - 2) {
        return setActive(entries[entries.length - 1].id);
      }
      let current = entries[0].id;
      for (const entry of entries) {
        if (entry.element.getBoundingClientRect().top > ACTIVATION_LINE_PX) break;
        current = entry.id;
      }
      setActive(current);
    };
    const onScroll = () => {
      if (!jumping.current) pinned.current = null;
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [entries]);

  const jumpTo = useCallback((entry: OutlineEntry, behavior: ScrollBehavior) => {
    pinned.current = entry.id;
    jumping.current = true;
    setActive(entry.id);
    const settle = () => {
      jumping.current = false;
    };
    // `scrollend` never fires when the group is already in place; the timer
    // covers that and browsers without the event.
    window.addEventListener("scrollend", settle, { once: true });
    window.setTimeout(settle, 1000);
    entry.element.scrollIntoView({ behavior, block: "start" });
  }, []);

  return { active, jumpTo };
}

/** Long enough for a lazy editor or a late query above the group to land. */
const ARRIVAL_HOLD_MS = 5000;

/**
 * The current page's groups as in-page links, under the active rail item.
 *
 * Each link is a real `#id` anchor (shareable, middle-clickable); a plain
 * click scrolls smoothly and rewrites the fragment without a history entry. A
 * URL that arrives with a fragment scrolls to its group once the group has
 * rendered, which the browser cannot do itself: the form loads after the
 * document does. Content above the group can still grow after that (the
 * Markdown editor loads on its own), so the group is held in place until the
 * reader scrolls, presses a key or a few seconds pass.
 */
export function SettingsOutlineList() {
  const t = useTranslations("kit.settings");
  const entries = useContext(EntriesContext);
  const listed = entries.length >= MIN_GROUPS;
  const { active, jumpTo } = useActiveGroup(listed ? entries : NO_ENTRIES);
  const arrivedAt = useRef<string | null>(null);
  const releaseHold = useRef<(() => void) | null>(null);
  const reduceMotion = usePrefersReducedMotion();

  useEffect(() => () => releaseHold.current?.(), []);

  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id || arrivedAt.current === window.location.href) return;
    const target = entries.find((entry) => entry.id === id);
    if (!target) return;
    arrivedAt.current = window.location.href;
    releaseHold.current?.();
    releaseHold.current = holdScrollPosition(() => jumpTo(target, "auto"), ARRIVAL_HOLD_MS);
  }, [entries, jumpTo]);

  if (!listed) return null;

  const onClick = (event: MouseEvent<HTMLAnchorElement>, entry: OutlineEntry) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    window.history.replaceState(null, "", `#${entry.id}`);
    arrivedAt.current = window.location.href;
    jumpTo(entry, reduceMotion ? "auto" : "smooth");
  };

  return (
    <ul aria-label={t("outline")} className="mb-1 ml-2 mt-1 border-l border-border">
      {entries.map((entry) => {
        const isActive = entry.id === active;
        return (
          <li key={entry.id}>
            <a
              href={`#${entry.id}`}
              aria-current={isActive ? "true" : undefined}
              onClick={(event) => onClick(event, entry)}
              className={cn(
                "-ml-px block truncate border-l py-1 pl-3 pr-2 text-caption transition-colors",
                "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                isActive
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {entry.title}
            </a>
          </li>
        );
      })}
    </ul>
  );
}
