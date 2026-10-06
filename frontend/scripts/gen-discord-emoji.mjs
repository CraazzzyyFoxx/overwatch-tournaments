/**
 * Renders the Discord bot's emoji set into backend/discord-service/assets/emoji/.
 *
 *   node scripts/gen-discord-emoji.mjs
 *
 * Roles are the site's own pictures (public/roles), tinted with the role
 * colours of globals.css (--aqt-tank / --aqt-damage / --aqt-support / --aqt-flex):
 * the white originals vanish on Discord's light theme. Everything else is a
 * lucide icon -- the set the site already draws with -- stroked in the matching
 * --aqt-* hue, so one picture reads on both Discord themes without a backdrop.
 * Names are shared/domain/discord_ui.py's EMOJI keys; upload them with
 * `python -m src.tools.emoji_sync` (backend/discord-service).
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as lucide from "lucide-react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import sharp from "sharp";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(FRONTEND, "..", "backend", "discord-service", "assets", "emoji");
const SIZE = 128;
// Discord shows an emoji at ~22-48 px; a slightly heavier stroke than the
// site's 2 keeps lucide's lines from thinning out at that size.
const STROKE = 2.5;

/** hsl(h s% l%) -> #rrggbb, so the palette is copied from globals.css as written. */
function hsl(h, s, l) {
  s /= 100;
  l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return `#${[f(0), f(8), f(4)].map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("")}`;
}

// globals.css :root --aqt-* tokens.
const C = {
  tank: hsl(209, 82, 65),
  damage: hsl(337, 81, 66),
  support: hsl(150, 57, 52),
  violet: hsl(270, 70, 62),
  emerald: hsl(150, 57, 52),
  up: hsl(146, 60, 58),
  amber: hsl(36, 88, 65),
  rose: hsl(349, 84, 63),
  blue: hsl(215, 83, 66),
  teal: hsl(172, 70, 49),
  gold: hsl(42, 63, 60),
  silver: hsl(212, 21, 73),
  dim: hsl(213, 9, 58),
};

/** name -> [lucide icon, colour]. */
const ICONS = {
  ok: ["CircleCheck", C.emerald],
  warn: ["TriangleAlert", C.amber],
  error: ["CircleX", C.rose],
  info: ["Info", C.blue],
  lock: ["Lock", C.amber],
  clock: ["Clock", C.dim],
  offline: ["Unplug", C.amber],
  pool: ["CircleDot", C.emerald],
  bench: ["Armchair", C.amber],
  starter: ["Star", C.gold],
  live: ["Radio", C.rose],
  host: ["Crown", C.gold],
  cohost: ["BadgeCheck", C.silver],
  map: ["Map", C.teal],
  players: ["Users", C.teal],
  vs: ["Swords", C.rose],
  trophy: ["Trophy", C.gold],
  points: ["TrendingUp", C.up],
  join: ["UserPlus", C.emerald],
  leave: ["LogOut", C.rose],
  edit: ["Pencil", C.blue],
  link: ["ExternalLink", C.blue],
  bell_off: ["BellOff", C.dim],
};

/** Lobby badges: lucide has no letters, so a lucide-style square with the letter drawn as strokes. */
const LETTERS = {
  lobby_a: ["M8.5 17 12 7l3.5 10M9.7 13.5h4.6", C.blue],
  lobby_b: ["M9.5 7v10h3.25a2.5 2.5 0 0 0 0-5H9.5h2.75a2.5 2.5 0 0 0 0-5Z", C.violet],
};

const ROLES = {
  tank: ["Tank.png", C.tank],
  damage: ["Damage.png", C.damage],
  support: ["Support.png", C.support],
  flex: ["Flex.svg", C.violet],
};

function png(svg) {
  return sharp(Buffer.from(svg), { density: 384 }).resize(SIZE, SIZE).png().toBuffer();
}

function lucideSvg(name, color) {
  const Icon = lucide[name];
  if (!Icon) throw new Error(`lucide-react has no ${name}`);
  return renderToStaticMarkup(createElement(Icon, { size: SIZE, color, strokeWidth: STROKE }));
}

function letterSvg(path, color) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${SIZE}" height="${SIZE}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${STROKE}" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="${path}"/></svg>`;
}

/** The role picture's own silhouette, filled with the role colour and centred on a square. */
async function role(file, color) {
  const source = await readFile(join(FRONTEND, "public", "roles", file));
  const inner = Math.round(SIZE * 0.84);
  // The originals sit in wide transparent margins; trimmed first, the role
  // fills the same square a lucide icon does.
  const trimmed = await sharp(source, { density: 384 }).png().trim().toBuffer();
  const glyph = await sharp(trimmed)
    .resize(inner, inner, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .ensureAlpha()
    .png()
    .toBuffer();
  const alpha = await sharp(glyph).extractChannel("alpha").toBuffer();
  const tinted = await sharp({ create: { width: inner, height: inner, channels: 3, background: color } })
    .joinChannel(alpha)
    .png()
    .toBuffer();
  const pad = Math.round((SIZE - inner) / 2);
  return sharp({ create: { width: SIZE, height: SIZE, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
    .composite([{ input: tinted, left: pad, top: pad }])
    .png()
    .toBuffer();
}

await mkdir(OUT, { recursive: true });
const jobs = [
  ...Object.entries(ROLES).map(([name, [file, color]]) => [name, () => role(file, color)]),
  ...Object.entries(ICONS).map(([name, [icon, color]]) => [name, () => png(lucideSvg(icon, color))]),
  ...Object.entries(LETTERS).map(([name, [path, color]]) => [name, () => png(letterSvg(path, color))]),
];
for (const [name, render] of jobs) {
  const bytes = await render();
  await writeFile(join(OUT, `${name}.png`), bytes);
  console.log(`${name}.png  ${bytes.length} B`);
}
