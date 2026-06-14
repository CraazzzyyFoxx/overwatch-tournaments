# Hero rendering convention

**All hero icons in the app must be rendered through these components — never a
raw `<img>` / `next/image` for a hero portrait.** Single hero → `HeroImage`,
group of heroes → `HeroStrip` (an overlapping `AvatarStack`).

## Components

- **`HeroImage`** (`@/components/hero/HeroImage`) — a single hero, built on the
  shadcn **`Avatar`** primitive (image with an initials fallback tinted by role).
  Props:
  - `hero` — `{ name, image_path, role, type?, color? }`
  - `size` — `"sm" | "md" | "lg"` (26 / 30 / 40px) **or** an explicit pixel number
  - `rounded` — `"full"` (default) | `"lg"`
  - `popover` — optional hover content (stats card, etc.); makes the avatar an
    interactive trigger with mouse hover-intent
- **`HeroStrip`** — multiple heroes as an overlapping stack that collapses to a
  `+N` bubble after `limit` (**default 5**, customizable). Optional
  `renderPopover(hero, index)` attaches a per-hero popover.
- **`AvatarStack`** (`@/components/ui/avatar`) — generic overlapping avatar stack
  (`max` default 5, plus `size` / `overlap` / `ringColor`, and the `+N` overflow
  bubble). Use it for any avatar group, not just heroes.

## Attaching statistics

Pass `popover` to `HeroImage` (or `renderPopover` to `HeroStrip`). For the
standard hero-on-map stats card use **`HeroStatsPopover`**
(`@/components/hero/HeroStatsPopover`) — this is the pattern used on the Maps tab:

```tsx
<HeroImage hero={hs.hero} size="sm" popover={<HeroStatsPopover stats={hs} />} />

// or a whole strip with stats on each avatar:
<HeroStrip heroes={heroes} renderPopover={(h, i) => <HeroStatsPopover stats={statsFor(h)} />} />
```

## Rules

1. Single hero → `HeroImage`; group → `HeroStrip` / `AvatarStack`.
2. Default collapse threshold is **5**; override via `limit` (HeroStrip) / `max` (AvatarStack).
3. Never render a hero portrait with a raw `<img>` / `next/image`.
4. To show stats on hover, attach `HeroStatsPopover` (or any node) via `popover`.
