import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "bun:test";

const componentPath = join(import.meta.dir, "VirtualParticipantsList.tsx");
const source = existsSync(componentPath) ? readFileSync(componentPath, "utf8") : "";
const pageSource = readFileSync(join(import.meta.dir, "../TournamentParticipantsPage.tsx"), "utf8");
const cssSource = readFileSync(join(import.meta.dir, "../../TournamentDetail.module.css"), "utf8");

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
    expect(source).toContain("virtualItems.map");
    expect(source).not.toContain("registrations.map");
  });

  it("derives document scroll margin without creating another vertical viewport", () => {
    expect(source).toContain("ResizeObserver");
    expect(source).toContain("getBoundingClientRect().top + window.scrollY");
    expect(source).toContain("observer.disconnect()");
    expect(cssSource).toMatch(/\.participantsTableViewport\s*\{[^}]*overflow-x:\s*auto/s);
    expect(cssSource).not.toMatch(/\.participants[^}]*overflow-y:\s*(auto|scroll)/s);
    expect(cssSource).not.toMatch(/\.participants[^}]*max-height/s);
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
    expect(source).not.toContain("index > 1 && styles.participantDetailCell");
    expect(source).not.toMatch(/<span className=\{styles\.participantCellValue\}>/);
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
    expect(pageSource).toContain("listQuery.isFetching");
    expect(pageSource).toContain("listQuery.refetch()");
  });

  it("maps virtual items rather than the complete registration payload", () => {
    expect(source).toContain("const virtualItems = virtualizer.getVirtualItems()");
    expect(source).toMatch(/virtualItems\.map[\s\S]*column\.render/);
  });
});
