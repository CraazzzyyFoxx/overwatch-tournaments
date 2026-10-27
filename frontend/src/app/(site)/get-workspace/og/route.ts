import { getTranslations } from "next-intl/server";

import { renderLandingOg } from "@/lib/og/landing";

// The organizer page's share card, named by its metadata (`page.tsx`); a route
// like `/`'s, so both landings serve their card the same way.
export async function GET() {
  const t = await getTranslations("getWorkspace.hero");
  return renderLandingOg({
    title: t.markup("title", { accent: (chunks) => chunks }),
    lede: t("lede")
  });
}
