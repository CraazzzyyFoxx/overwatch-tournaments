import { getTranslations } from "next-intl/server";

import { renderLandingOg } from "@/lib/og/landing";

// `/`'s share card. A route, not an `opengraph-image` file: the file would put
// the platform's card on every community host's `/` too, while this URL is
// named only by the apex branch of `page.tsx`'s metadata. It says what the hero
// says: its h1 (`home.hero.title`) and its lede.
export async function GET() {
  const t = await getTranslations("home.hero");
  return renderLandingOg({
    title: t.markup("title", { accent: (chunks) => chunks }),
    lede: t("lede")
  });
}
