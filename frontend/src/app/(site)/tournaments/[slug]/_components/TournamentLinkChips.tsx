"use client";

import { FileText, Link2, ListVideo, MessagesSquare, Network } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ComponentType } from "react";

import type { TournamentLink, TournamentLinkKind } from "@/types/stream.types";
import { TOURNAMENT_ACTION_CLASS } from "./tournamentActionClass";

type TournamentLinkChipsProps = {
  /** `tournament.links` — absent whenever the read did not ask for the entity. */
  links: TournamentLink[] | undefined;
  className?: string;
};

/** Message keys, spelled out because next-intl types reject a widened key. */
type ChipLabelKey =
  | "tournamentDetail.links.kinds.discord"
  | "tournamentDetail.links.kinds.vod"
  | "tournamentDetail.links.kinds.bracket"
  | "tournamentDetail.links.kinds.rules"
  | "tournamentDetail.links.kinds.other";

type ChipMeta = {
  labelKey: ChipLabelKey;
  icon: ComponentType<{ className?: string }>;
};

/**
 * Every link kind, keyed by kind rather than resolved through a chain of
 * ternaries — the reason `STREAM_STATUS_META` and `TOURNAMENT_STATUS_META` are
 * registries: a kind added to `TOURNAMENT_LINK_KINDS` on the backend then fails
 * the build here instead of rendering a raw enum token to spectators.
 *
 * `stream` maps to `null` — not omitted from the type, so this stays exhaustive
 * over the backend vocabulary, and not merely skipped at the call site. Official
 * broadcasts belong to `TournamentBroadcastDock`, which renders them with live
 * status and a player; a second copy here carrying neither would be worse than
 * their absence.
 */
const CHIP_META: Record<TournamentLinkKind, ChipMeta | null> = {
  stream: null,
  discord: { labelKey: "tournamentDetail.links.kinds.discord", icon: MessagesSquare },
  vod: { labelKey: "tournamentDetail.links.kinds.vod", icon: ListVideo },
  bracket: { labelKey: "tournamentDetail.links.kinds.bracket", icon: Network },
  rules: { labelKey: "tournamentDetail.links.kinds.rules", icon: FileText },
  other: { labelKey: "tournamentDetail.links.kinds.other", icon: Link2 },
};

/**
 * A `bracket` link that only leads back to this site's own bracket section. The
 * rail has that tab and the overview previews the bracket with its own link, so
 * a chip for it is the third copy of one address. The organizer's EXTERNAL
 * bracket (Challonge, Battlefy) is why the kind exists, and stays.
 *
 * Matched on the path alone: the link may be stored relative, the public site
 * answers on more than one hostname, and `window.location` does not exist in
 * the server render this list also runs in.
 */
const INTERNAL_BRACKET_PATH = /^\/tournaments\/[^/]+\/bracket(?:[/?#]|$)/;

function isInternalBracketLink(link: TournamentLink): boolean {
  return (
    link.kind === "bracket" &&
    INTERNAL_BRACKET_PATH.test(link.url.trim().replace(/^[a-z]+:\/\/[^/]+/i, ""))
  );
}

/**
 * The links that actually render as chips: active, not a link back into this
 * page (see above), and with a chip in the registry (`stream` has none —
 * official broadcasts belong to the dock).
 *
 * Ordered by `(sort_order, id)` — the same order the backend returns and the
 * organizer sets in the admin Links tab, mirrored here so a client-side sort can
 * never disagree with the table they were just looking at.
 *
 * Exported because the caller has to decide whether to draw a heading around
 * them: the component renders nothing for an empty set, but a card's title and
 * hairline would still be on screen above it.
 */
export function visibleTournamentLinks(links: TournamentLink[] | undefined) {
  // `flatMap` rather than filter-then-index: it resolves the registry entry once
  // and carries it forward, so the render needs neither a second lookup nor a
  // cast to convince the compiler the entry is there.
  return (links ?? [])
    .flatMap((link) => {
      const meta = link.is_active && !isInternalBracketLink(link) ? CHIP_META[link.kind] : null;
      return meta ? [{ link, meta }] : [];
    })
    .sort((a, b) => a.link.sort_order - b.link.sort_order || a.link.id - b.link.id);
}

/**
 * Everything around the event that is not the broadcast: the Discord invite, the
 * rules doc, an external bracket, VOD playlists.
 *
 * Rendered in the overview's Links card, not in the page header. They are
 * reference material a reader consults once, and the header's job is the state
 * of the tournament plus what a reader can act on — a header that also carried
 * five translucent chips put them on top of the cover banner, where a
 * `--aqt-overlay-2` box has no surface to sit on.
 */
export function TournamentLinkChips({ links, className }: Readonly<TournamentLinkChipsProps>) {
  const t = useTranslations();

  const chips = visibleTournamentLinks(links);

  // Nothing at all rather than an empty heading: this is a public page, and "the
  // organizer has not added links" is not news a spectator came for. The admin
  // Links tab is where absence is worth stating.
  if (chips.length === 0) {
    return null;
  }

  return (
    <nav aria-label={t("tournamentDetail.links.heading")} className={className}>
      <ul className="m-0 flex list-none flex-wrap items-center gap-2.5 p-0">
        {chips.map(({ link, meta }) => {
          const Icon = meta.icon;
          return (
            <li key={link.id}>
              <a
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className={TOURNAMENT_ACTION_CLASS}
              >
                <Icon className="size-4 opacity-80" aria-hidden />
                {/* `label` is NULL-able with exactly this meaning (see the column
                    docstring): fall back to the kind's own name, never to the raw
                    URL, which would put a tracking query string on screen. */}
                <span>{link.label?.trim() || t(meta.labelKey)}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default TournamentLinkChips;
