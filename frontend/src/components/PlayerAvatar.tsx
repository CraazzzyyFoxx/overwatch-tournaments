import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn, initials } from "@/lib/utils";

/** The minimum a surface needs to draw a player's identity. */
export interface PlayerIdentity {
  id: number;
  name: string;
  avatar_url: string | null;
}

/**
 * A player's avatar, or their initials when there is none (or it fails to load).
 *
 * Decorative by default: the player's name sits beside it, so the whole avatar is
 * hidden from assistive technology. `named` is for an avatar that stands in for the
 * name (a presence stack): it then carries the name as its alt text and title.
 */
export function PlayerAvatar({
  user,
  size = 32,
  named = false,
  className
}: Readonly<{ user: Pick<PlayerIdentity, "name" | "avatar_url">; size?: number; named?: boolean; className?: string }>) {
  return (
    <Avatar
      aria-hidden={named ? undefined : true}
      title={named ? user.name : undefined}
      className={cn("shrink-0 border border-[color:var(--aqt-border)]", className)}
      style={{ width: size, height: size }}
    >
      {user.avatar_url ? <AvatarImage src={user.avatar_url} alt={named ? user.name : ""} /> : null}
      <AvatarFallback className="font-bold">
        {initials(user.name)}
      </AvatarFallback>
    </Avatar>
  );
}
