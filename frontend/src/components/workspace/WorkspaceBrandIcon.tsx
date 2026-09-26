import { cn, initials } from "@/lib/utils";

interface WorkspaceBrandIconProps {
  name: string;
  iconUrl: string | null;
  /** Size / rounding / font-size utilities; the base look is fixed. */
  className?: string;
}

/**
 * Workspace branding glyph: the workspace icon when set, otherwise a teal
 * initials tile. Used wherever white-label (tenant) chrome replaces the
 * platform logo — the header, the mobile burger sheet, the auth modal.
 */
const WorkspaceBrandIcon = ({ name, iconUrl, className }: WorkspaceBrandIconProps) =>
  iconUrl ? (
    // Plain <img> (not next/image) to avoid remote-domain config for
    // arbitrary workspace icon hosts — same pattern as the switcher.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={iconUrl} alt="" className={cn("shrink-0 object-cover", className)} />
  ) : (
    <span
      className={cn(
        "grid shrink-0 place-items-center bg-(--aqt-teal) font-semibold text-[color:var(--aqt-bg)]",
        className
      )}
    >
      {initials(name)}
    </span>
  );

export default WorkspaceBrandIcon;
