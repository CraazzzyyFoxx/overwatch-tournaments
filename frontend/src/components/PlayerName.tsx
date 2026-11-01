import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { getPlayerSlug, getPlayerType } from "@/lib/player";
import type { RoleRef } from "@/lib/roster/role-ref";
import { cn } from "@/lib/utils";
import type { PersonDisplay } from "@/types/user.types";

type TagMode = "muted" | "hidden";

/** The full shown text: name plus its `#tag`. */
const fullName = (display: PersonDisplay) => display.name + (display.tag ?? "");

/** Hover text: the canonical name when it differs from what is shown, then the event-time name when it differs. */
function usePersonTitle(display: PersonDisplay): string | undefined {
  const t = useTranslations("common");
  const lines = [
    display.canonical && display.canonical !== fullName(display) ? display.canonical : null,
    display.snapshot ? t("personSnapshot", { name: display.snapshot }) : null
  ].filter(Boolean);
  return lines.length > 0 ? lines.join("\n") : undefined;
}

/**
 * A person's name as one truncating line: the name, then its `#tag` in `--aqt-fg-faint` (DESIGN §4), so an ellipsis
 * eats the tag first. `tag="hidden"` drops it (OG images, dense cells); `showCanonical` appends the canonical name,
 * muted, when it differs (admin). `truncate` needs a block box: a flex/grid parent gives one, else pass `block`.
 */
export function PersonLabel({
  display,
  tag = "muted",
  showCanonical = false,
  className,
  tagClassName
}: Readonly<{
  display: PersonDisplay;
  tag?: TagMode;
  showCanonical?: boolean;
  className?: string;
  tagClassName?: string;
}>) {
  const title = usePersonTitle(display);
  const canonical = showCanonical && display.canonical && display.canonical !== fullName(display) ? display.canonical : null;
  return (
    <span title={title} className={cn("min-w-0 truncate", className)}>
      <bdi>{display.name}</bdi>
      {tag === "muted" && display.tag ? (
        <span className={cn("font-normal text-[color:var(--aqt-fg-faint)]", tagClassName)}>{display.tag}</span>
      ) : null}
      {canonical ? (
        <span className="ms-1.5 font-normal text-[color:var(--aqt-fg-faint)]">
          (<bdi>{canonical}</bdi>)
        </span>
      ) : null}
    </span>
  );
}

/**
 * A person's name (`PersonLabel`) linking to their profile by the canonical name, with their role under it on
 * request. Unlinked when `link` is off or there is no canonical name. `className` sets the block's width or size.
 */
const PlayerName = ({
  display,
  role,
  includeSpecialization = false,
  link = true,
  tag,
  showCanonical,
  className
}: {
  display: PersonDisplay;
  role?: RoleRef | null;
  includeSpecialization?: boolean;
  link?: boolean;
  tag?: TagMode;
  showCanonical?: boolean;
  className?: string;
}) => {
  const label = <PersonLabel display={display} tag={tag} showCanonical={showCanonical} className="block font-semibold" />;
  return (
    <div className={cn("min-w-0 text-base", className)}>
      {link && display.canonical ? (
        // Hover/focus prefetch: a roster or a player index renders dozens of these at once.
        <HoverPrefetchLink
          href={`/users/${getPlayerSlug(display.canonical)}`}
          className="block min-w-0 transition-colors hover:text-[color:var(--aqt-teal)]"
        >
          {label}
        </HoverPrefetchLink>
      ) : (
        label
      )}
      {includeSpecialization && role !== undefined && (
        <p className="text-xs text-muted-foreground">{getPlayerType({ role })}</p>
      )}
    </div>
  );
};

export default PlayerName;
