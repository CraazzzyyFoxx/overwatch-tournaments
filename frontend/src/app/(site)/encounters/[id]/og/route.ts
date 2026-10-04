import { renderEncounterOg } from "@/lib/og/encounter";

// The URL the Discord card embeds. Not `opengraph-image`: under the `(site)`
// route group Next serves that at a hashed path (`opengraph-image-<hash>`),
// which a backend cannot spell. The card's `?v=<hash>` cache buster is ignored.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return renderEncounterOg(Number(id));
}
