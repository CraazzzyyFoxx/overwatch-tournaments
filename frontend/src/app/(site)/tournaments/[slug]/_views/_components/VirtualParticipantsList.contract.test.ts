import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const componentPath = join(import.meta.dirname, "VirtualParticipantsList.tsx");
const source = existsSync(componentPath) ? readFileSync(componentPath, "utf8") : "";
const pageSource = [
  readFileSync(join(import.meta.dirname, "../TournamentParticipantsPage.tsx"), "utf8"),
  readFileSync(join(import.meta.dirname, "TournamentParticipantsView.tsx"), "utf8")
].join("\n");

describe("virtual participants collection", () => {
  it("uses one window virtualizer with measured stable registration rows", () => {
    expect(source).toContain("useWindowVirtualizer");
    expect(source).toMatch(/getItemKey:\s*\(?index\)?\s*=>\s*registrations\[index\]\.id/);
    expect(source).toContain("overscan: 8");
    expect(source).toContain("scrollMargin");
    expect(source).toContain("data-index");
    expect(source).toContain("virtualizer.measureElement");
    expect(source).toContain("item.start - scrollMargin");
    expect(source).toContain("virtualizer.getTotalSize()");
    expect(source).toContain("rows.map");
  });

  it("mounts every row for native find-in-page without stealing the shortcut", () => {
    // event.code survives non-latin layouts; preventDefault must stay absent so
    // the browser still opens its own find bar.
    expect(source).toContain('event.code === "KeyF"');
    expect(source).toContain("event.ctrlKey || event.metaKey");
    expect(source).not.toMatch(/KeyF[\s\S]{0,200}preventDefault/);
    expect(source).toMatch(/findMode[\s\S]*registrations\.map/);
    expect(source).toContain("findMode ? undefined : virtualizer.measureElement");
  });

  it("derives document scroll margin without creating another vertical viewport", () => {
    expect(source).toContain("ResizeObserver");
    expect(source).toContain("getBoundingClientRect().top + window.scrollY");
    expect(source).toContain("observer.disconnect()");
  });

  it("exposes the full logical table and stable expandable row semantics", () => {
    expect(source).toContain('role="table"');
    expect(source).toContain("aria-rowcount={registrations.length + 1}");
    expect(source).toContain("aria-rowindex={item.index + 2}");
    expect(source).toContain("participant-details-${registration.id}");
    expect(source).toContain("participant-expander-${registration.id}");
    expect(source).toContain("aria-controls={detailsId}");
    expect(source).toContain("aria-expanded={expanded}");
    expect(source).toContain("event.currentTarget.focus()");
  });

  it("migrates the page away from local storage, full DOM rendering, and spinner loading", () => {
    expect(pageSource).toContain("useSearchParams");
    expect(pageSource).toContain("VirtualParticipantsList");
    expect(pageSource).toContain("TournamentParticipantsSkeleton");
    expect(pageSource).not.toContain("useLocalStorageState");
    expect(pageSource).not.toContain("useColumnVisibility");
    expect(pageSource).not.toContain("filtered.map");
    expect(pageSource).not.toMatch(/pagination|pageSize|currentPage/i);
    expect(pageSource).toContain("useParticipantSearchInput");
    expect(pageSource).toContain("maxLength={PARTICIPANT_SEARCH_MAX_LENGTH}");
    expect(pageSource).not.toContain("maxLength={160}");
    expect(pageSource).not.toContain("searchTimerRef");
    expect(pageSource).toContain("allowedStatuses");
    expect(pageSource).toContain("displayedStatuses");
  });

  it("keeps one polite result announcement and distinct true/filtered empty states", () => {
    expect(pageSource.match(/aria-live="polite"/g)).toHaveLength(1);
    expect(pageSource).toContain("filteredEmpty");
    expect(pageSource).toContain("trueEmpty");
    expect(pageSource).toContain("listQuery.refetch()");
  });

  it("maps virtual items rather than the complete registration payload", () => {
    expect(source).toContain("const virtualItems = virtualizer.getVirtualItems()");
    expect(source).toMatch(/rows\.map[\s\S]*column\.render/);
  });
});
