/** Hero name-initials helper. Role helpers moved to `@/lib/roster/player-role`. */
export const heroInitials = (name: string): string => {
  if (!name) return "?";
  const parts = name.replace(/[^A-Za-zА-Яа-я0-9]/g, " ").trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
};
