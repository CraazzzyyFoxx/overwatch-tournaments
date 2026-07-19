import { cn } from "@/lib/utils";

/** 1–2 letter initials from a workspace name, for icon fallbacks. */
export function workspaceInitials(name: string): string {
  return name
    .split(/[\s-]+/)
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
}

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
        "grid shrink-0 place-items-center bg-(--aqt-teal) font-semibold text-black",
        className
      )}
    >
      {workspaceInitials(name)}
    </span>
  );

export default WorkspaceBrandIcon;
