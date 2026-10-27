import type { ReactNode } from "react";

import Image from "@/components/ui/image";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

/**
 * Stand-in for a tournament with no cover, no map played and no map still of its game.
 *
 * Not a placeholder but a last kind of cover: the tournament's own name, set
 * large on a teal-tinted wash. The earlier abstract grid-and-glow panel said
 * nothing — a third of the grid was interchangeable dark rectangles.
 *
 * `aria-hidden` because the name is already the card's heading; this is the
 * same fact drawn, not a second announcement. The logo, when there is one,
 * still renders over it.
 */
const CoverFallback = ({ name }: { name: string }) => (
  <span
    aria-hidden
    data-cover-fallback
    /* `z-[2]`: the scrim below exists for uploaded artwork; over this surface
       it would only grey out the name it is drawn from. */
    className="absolute inset-0 z-[2] flex items-center justify-center overflow-hidden px-4 text-center"
    style={{
      background:
        "linear-gradient(135deg, color-mix(in srgb, var(--aqt-teal) 18%, var(--aqt-bg-2)), var(--aqt-bg) 78%)"
    }}
  >
    <span className="absolute inset-x-0 top-0 z-[2] h-0.5 bg-[color:var(--aqt-teal)]" />
    <span
      data-cover-name
      className="line-clamp-3 font-onest text-[clamp(1.05rem,2.4vw,1.5rem)] font-bold leading-tight text-[color:color-mix(in_srgb,var(--aqt-fg)_72%,transparent)]"
    >
      {name}
    </span>
  </span>
);

/**
 * A tournament's picture in a 16:9 clipping frame: the caller's
 * `tournamentPicture` (`lib/tournament/art.ts`, the home page's rule too), else
 * the drawn name; the logo in the bottom-left corner. The tournament list's
 * cards draw it.
 *
 * The caller styles the frame (radius, border); `children` are overlays on it
 * (the list card's status chip). Both images are `alt=""`: the name and facts
 * beside the cover carry every fact the picture does.
 */
export function TournamentCover({
  tournament,
  picture,
  sizes,
  className,
  children
}: Readonly<{
  tournament: Pick<Tournament, "name" | "logo_url">;
  /**
   * `tournamentPicture`'s answer. `undefined` while its reads are out: the
   * frame stays empty rather than flash the drawn name before the map lands.
   */
  picture: string | null | undefined;
  /** The `sizes` of the picture, from the caller's layout. */
  sizes: string;
  className?: string;
  children?: ReactNode;
}>) {
  return (
    <div className={cn("relative aspect-video w-full overflow-hidden bg-[color:var(--aqt-bg-2)]", className)}>
      {picture ? (
        <Image
          src={picture}
          alt=""
          aria-hidden
          data-cover
          fill
          sizes={sizes}
          loading="lazy"
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : picture === undefined ? null : (
        <CoverFallback name={tournament.name} />
      )}

      {/* Scrim: the logo sits on artwork we do not control, so the contrast
          under it cannot be left to the image. */}
      <span
        aria-hidden
        className="absolute inset-x-0 bottom-0 z-[1] h-2/3 bg-gradient-to-t from-[color:var(--aqt-bg)] via-[color:color-mix(in_srgb,var(--aqt-bg)_55%,transparent)] to-transparent"
      />

      {tournament.logo_url ? (
        <Image
          src={tournament.logo_url}
          alt=""
          aria-hidden
          data-logo
          width={40}
          height={40}
          loading="lazy"
          decoding="async"
          className="absolute bottom-2 left-2 z-[2] size-10 rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] object-cover"
        />
      ) : null}

      {children}
    </div>
  );
}
