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

/** Group letters in enumeration order. The Cyrillic run skips the letters
 *  nobody numbers groups with (Ё, Й, Ъ, Ы, Ь), so "Группа К" is the tenth. */
const LATIN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const CYRILLIC_LETTERS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ";

/**
 * The group's 0-based position, read from its own label, the last word:
 * "B", "Group B", "Группа Б" and "2" are all 1. `null` when the label is not a
 * single letter or a positive number ("Playoffs", "Upper").
 */
export function groupIndex(name?: string | null): number | null {
  const label = name?.trim().split(/\s+/).at(-1)?.toUpperCase() ?? "";
  if (/^\d+$/.test(label)) {
    const number = Number(label);
    return number > 0 ? number - 1 : null;
  }
  if (label.length !== 1) return null;
  const latin = LATIN_LETTERS.indexOf(label);
  if (latin >= 0) return latin;
  const cyrillic = CYRILLIC_LETTERS.indexOf(label);
  return cyrillic >= 0 ? cyrillic : null;
}

/** Accent tokens a group cycles through; neighbours never share a hue. */
const GROUP_HUES = [
  "var(--aqt-teal)",
  "var(--aqt-amber)",
  "var(--aqt-violet)",
  "var(--aqt-blue)",
  "var(--aqt-rose)",
  "var(--aqt-emerald)"
];

/**
 * The group's accent colour. Any number of groups works: the palette repeats
 * every six, and an unnumbered group takes the first hue.
 */
export function groupHue(name?: string | null): string {
  return GROUP_HUES[(groupIndex(name) ?? 0) % GROUP_HUES.length];
}

