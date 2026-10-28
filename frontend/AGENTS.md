<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Design system

Before any UI work, read [`DESIGN.md`](DESIGN.md): tokens, type roles, the components to reuse, layout and canonical patterns. Its chip policy (§4) is strict — a chip only for a filter, a lifecycle status, a colour key or a count; every other fact is plain text.

Controls come from `src/components/ui/` only: no native `<button>`, `<input>`, `<select>`, `<textarea>`, `<table>` or `<img>` in feature code, and no `text-*` / `font-*` / height overrides on a control — its `size` prop sets both (DESIGN.md §3, Control text). Missing a control? Add a variant or primitive to `components/ui/`. `bun run lint:design` (R8–R14) fails on a native control, table or image outside `ui/`, a hand-turned chevron, a `text-[Npx]`, a hand-drawn hairline and a hand-rolled spinner. A loading region draws its skeleton; a `Spinner` only marks a pending action, a running job or a background refetch (DESIGN.md §6, §9).
