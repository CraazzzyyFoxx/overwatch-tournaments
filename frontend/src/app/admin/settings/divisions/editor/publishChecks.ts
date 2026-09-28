import type { DivisionGridActivationReadiness } from "@/types/workspace.types";

import {
  bandsCoverLadder,
  floorsDescend,
  RANK_COUNT,
  unlinkedRanks,
  type Band,
  type Scale
} from "./draftReducer";

export interface PublishCheck {
  key: string;
  label: string;
  ok: boolean;
  /** A failing advisory is worth saying and does not stop a publish. */
  blocking: boolean;
}

export interface PublishCheckInput {
  bands: Band[];
  scale: Scale;
  readiness: DivisionGridActivationReadiness | null;
  /** Mapping rows with no primary target yet, from `unresolvedRows`. */
  unresolvedMappings: number;
  /** `false` until the draft has been saved and its tiers have ids. */
  mappable: boolean;
  dirty: boolean;
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/**
 * The pre-flight list behind "Ready to publish?" — and the Publish button's
 * enablement. One computation, two consumers, so the reason a publish is
 * refused is always on screen next to the disabled button.
 *
 * The OW coverage is checked rather than assumed on both scales: a rank no
 * division takes is a player whose OverFast snapshot silently resolves to
 * nothing, and a ladder band out of place would re-band every player.
 */
export function publishChecks({
  bands,
  scale,
  readiness,
  unresolvedMappings,
  mappable,
  dirty
}: PublishCheckInput): PublishCheck[] {
  const names = bands.map((band) => band.name.trim().toLowerCase());
  const namesUnique = new Set(names).size === names.length && names.every((name) => name !== "");
  const borrowed = bands.filter((band) => band.icon_url === null).length;
  const incomplete = readiness
    ? readiness.incomplete_mapping_version_ids.length + readiness.missing_mapping_version_ids.length
    : 0;
  const open = unresolvedMappings + incomplete;
  const gaps = unlinkedRanks(bands).length;
  const unlinked = bands.filter((band) => band.ow === null).length;

  const coverage: PublishCheck[] =
    scale === "ladder"
      ? [
          {
            key: "coverage",
            label: `Every one of the ${RANK_COUNT} OW ranks belongs to exactly one division`,
            ok: bandsCoverLadder(bands),
            blocking: true
          }
        ]
      : [
          {
            key: "floors",
            label: "Rank ranges descend without gaps or overlaps",
            ok: floorsDescend(bands),
            blocking: true
          },
          {
            key: "coverage",
            label:
              gaps === 0
                ? `Every one of the ${RANK_COUNT} OW ranks links to a division`
                : `${plural(gaps, "OW rank links", "OW ranks link")} to no division`,
            ok: gaps === 0,
            blocking: true
          },
          {
            key: "unlinked",
            label:
              unlinked === 0
                ? "Every division has OW ranks"
                : `${plural(unlinked, "division has", "divisions have")} no OW ranks — only a stored rank reaches ${unlinked === 1 ? "it" : "them"}`,
            ok: unlinked === 0,
            blocking: false
          }
        ];

  return [
    ...coverage,
    {
      key: "names",
      label: `All ${bands.length} names are set and unique`,
      ok: namesUnique,
      blocking: true
    },
    {
      key: "saved",
      label: "The draft is saved as a version",
      ok: !dirty,
      blocking: true
    },
    {
      key: "crests",
      label:
        borrowed === 0
          ? "Every division has its own crest"
          : `${plural(borrowed, "division still borrows", "divisions still borrow")} a ladder crest`,
      ok: borrowed === 0,
      blocking: false
    },
    {
      key: "mappings",
      label:
        open === 0
          ? "Every older version maps onto this one"
          : `${plural(open, "mapping decision", "mapping decisions")} left in the Mappings tab`,
      // Before the first save there is nothing to map onto, and the "saved"
      // check above already reports that.
      ok: mappable ? open === 0 : false,
      blocking: true
    }
  ];
}

/** Whether the draft may be published at all — the blocking checks, all passing. */
export function readyToPublish(checks: PublishCheck[]): boolean {
  return checks.every((check) => check.ok || !check.blocking);
}
