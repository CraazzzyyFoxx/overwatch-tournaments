/**
 * How a group is named in a label.
 *
 * Organizers usually spell a group out in full ("Группа А", "Group A"), so
 * prefixing the word unconditionally printed "Group Группа А". Only a bare
 * label — a letter or a number — needs the word in front of it, which is the
 * rule the matches list already applied to `stage_item.name`.
 */
export function groupDisplayName(name: string, groupWord: string): string {
  const trimmed = name.trim();
  return trimmed.length <= 2 ? `${groupWord} ${trimmed}` : trimmed;
}
