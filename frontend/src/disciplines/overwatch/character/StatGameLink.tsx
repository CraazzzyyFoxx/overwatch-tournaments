"use client";

import { useRef } from "react";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useHoverIntent } from "@/hooks/useHoverIntent";
import type { CharacterStatBest } from "@/types/user.types";

/**
 * One game of a stat (the player's best, or the hero's record for every player) as a link to its match, with the map
 * (or the record's holder) under the value. Hover and keyboard focus open a card with the map, the tournament and
 * the holder; on a touch screen the first tap opens the card and the second, or the card's own link, goes to the match.
 */
export default function StatGameLink({
  game,
  value,
  holder = false
}: Readonly<{ game: CharacterStatBest; value: string; holder?: boolean }>) {
  const t = useTranslations("users.heroes");
  const { open, setOpen, cancel, scheduleOpen, scheduleClose } = useHoverIntent({ closeDelay: 120, exclusive: true });
  const anchor = useRef<HTMLAnchorElement>(null);
  // A press by touch or pen: its focus waits for the click, which opens the card instead of leaving the page.
  const touch = useRef(false);
  const href = `/encounters/${game.encounter_id}`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <HoverPrefetchLink
          ref={anchor}
          href={href}
          className="-mx-1.5 inline-flex max-w-40 flex-col items-end rounded-md px-1.5 py-0.5 text-right transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-[color:var(--aqt-teal)]"
          onPointerDown={(event) => {
            touch.current = event.pointerType !== "mouse";
          }}
          onPointerEnter={(event) => {
            if (event.pointerType === "mouse") scheduleOpen();
          }}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") scheduleClose();
          }}
          onFocus={() => {
            if (!touch.current) scheduleOpen(0);
          }}
          onBlur={() => {
            touch.current = false;
            scheduleClose(0);
          }}
          onClick={(event) => {
            if (touch.current && !open) {
              event.preventDefault();
              setOpen(true);
            }
          }}
        >
          <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">{value}</span>
          {holder ? (
            <HandleLabel handle={game.player_name} className="block max-w-full text-label text-[color:var(--aqt-fg-dim)]" />
          ) : (
            <span className="block max-w-full truncate text-label text-[color:var(--aqt-fg-dim)]">{game.map_name}</span>
          )}
        </HoverPrefetchLink>
      </PopoverAnchor>
      <PopoverContent
        side="top"
        className="w-64 overflow-hidden rounded-xl p-0"
        animate={false}
        // Focus stays on the link, which goes to the match on Enter; the card only shows where the game was.
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
        onInteractOutside={(event) => {
          if (anchor.current?.contains(event.target as Node)) event.preventDefault();
        }}
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") cancel();
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") scheduleClose();
        }}
      >
        {game.map_image_path ? (
          <div className="relative h-28 w-full">
            <Image src={game.map_image_path} alt="" fill sizes="256px" className="object-cover" />
          </div>
        ) : null}
        <div className="flex flex-col gap-1 px-3 py-2.5">
          <span className="text-body font-semibold text-[color:var(--aqt-fg)]">{game.map_name}</span>
          <span className="text-caption text-[color:var(--aqt-fg-muted)]">{game.tournament_name}</span>
          {holder ? (
            <span className="flex min-w-0 items-baseline gap-2">
              <Eyebrow>{t("recordHolder")}</Eyebrow>
              <HandleLabel handle={game.player_name} className="text-caption font-semibold text-[color:var(--aqt-fg)]" />
            </span>
          ) : null}
          <HoverPrefetchLink
            href={href}
            tabIndex={-1}
            className="mt-1 inline-flex items-center gap-1 self-start text-caption font-semibold text-[color:var(--aqt-teal)] hover:underline"
          >
            {t("openMatch")}
            <ArrowRight aria-hidden className="size-3.5" />
          </HoverPrefetchLink>
        </div>
      </PopoverContent>
    </Popover>
  );
}
