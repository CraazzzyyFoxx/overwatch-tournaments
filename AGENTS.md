# OWT — Overwatch tournaments monorepo

Documentation map: [`docs/README.md`](docs/README.md). Contribution rules: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Plans, specs, reviews

Never commit them — not to `docs/`, `docs/plans/`, `docs/superpowers/` or anywhere else; `docs/` is documentation only. Draft in gitignored scratch (`.claude/`, `.superpowers/`). Record decisions and their reasons in Graphiti, group `anak-tournaments`; facts that must outlive the work go into the evergreen docs. Comments citing `docs/plans/…`, `docs/superpowers/…`, `docs/reviews/…` point at removed files: search Graphiti or `git show 50b83c88f537:<path>`.

## Frontend

- Don't run `next build` for testing; `next lint` is enough.
- Never use native `<select>`/`<option>`. Always use the component-library select (`@/components/ui/select`: `Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem`).

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

<!-- GRAFT_START -->
## Graft

In repositories with a `graft/` directory at the repo root, Graft gives structural (tree-sitter, no LLM) code search and dependency graphs — complements CodeGraph, doesn't replace it:

- **MCP tools** (when available): `graft_find_code` (ranked nodes for a question, source inlined), `graft_file_api` (every signature in a file, no bodies), `graft_trace_calls` (callers/callees, blast radius), `graft_find_all` (exhaustive regex, grouped by symbol), `graft_repo_map` (directory clusters, hubs, hotspots), `graft_check_freshness`.
- **Shell** (always works): `graft ask "<question>"`, `graft grep "<regex>"`, `graft map`, `graft callers <symbol>` (add `--direction out` or `-d N`), `graft blast` (blast radius of a diff).
- The graph auto-refreshes against the working tree on every query (~3ms, structural, $0) — answers reflect uncommitted edits. Run `graft build` after large structural changes if a query looks stale; `graft build --deep` (needs `GRAFT_API_KEY`) adds LLM-written concept-node summaries, not required for the above.
- `graft/` is a local, git-ignored cache — never edit it by hand, never commit it.
<!-- GRAFT_END -->
