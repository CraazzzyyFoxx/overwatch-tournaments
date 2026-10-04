import { SITE_NAME } from "@/config/site";
import { OG_SIZE, renderEncounterOg } from "@/lib/og/encounter";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = `${SITE_NAME} pre-game room`;

// The room is one encounter's, so it unfurls as that encounter's card.
export default async function Image({
  params
}: {
  params: Promise<{ encounterId: string }>;
}) {
  const { encounterId } = await params;
  return renderEncounterOg(Number(encounterId));
}
