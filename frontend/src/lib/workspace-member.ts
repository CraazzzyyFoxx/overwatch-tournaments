import type { WorkspaceMember } from "@/types/workspace.types";

/**
 * Human-readable name for a workspace member, with graceful fallbacks:
 * full name -> username -> email -> `User #<id>`.
 */
export function memberDisplayName(member: WorkspaceMember | undefined, userId: number): string {
  if (!member) {
    return `User #${userId}`;
  }
  const fullName = [member.first_name, member.last_name].filter(Boolean).join(" ").trim();
  return fullName || member.username || member.email || `User #${userId}`;
}
