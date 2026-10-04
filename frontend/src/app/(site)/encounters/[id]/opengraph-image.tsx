import { SITE_NAME } from "@/config/site";
import { OG_SIZE, renderEncounterOg } from "@/lib/og/encounter";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = `${SITE_NAME} match`;

// The Discord card appends a `?v=<hash>` cache buster; a route ignores the
// query string, so the same image is served either way.
export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return renderEncounterOg(Number(id));
}
