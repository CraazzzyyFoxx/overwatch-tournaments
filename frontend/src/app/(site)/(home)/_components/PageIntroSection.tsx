import { getTranslations } from "next-intl/server";
import { BarChart3, Trophy } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Button } from "@/components/ui/button";
import { PageHero, HeroCoord } from "@/components/site/PageHero";

/** Cinematic page header. Its lede is the one thing a tenant host rewrites. */
export async function PageIntroSection({ tenantMode }: Readonly<{ tenantMode: boolean }>) {
  const t = await getTranslations();
  return (
    <PageHero
      align="center"
      eyebrow={<HeroCoord>{t("home.eyebrow")}</HeroCoord>}
      title={t.rich("home.title", { em: (chunks) => <em>{chunks}</em> })}
      lede={tenantMode ? t("home.ledeTenant") : t("home.ledePlatform")}
      actions={
        <>
          <Button asChild size="lg" className="shadow-lg shadow-primary/20">
            <HoverPrefetchLink href="/tournaments">
              <Trophy className="mr-2 h-5 w-5" aria-hidden />
              {t("home.browseTournaments")}
            </HoverPrefetchLink>
          </Button>
          <Button asChild variant="secondary" size="lg">
            <HoverPrefetchLink href="/tournaments/analytics">
              <BarChart3 className="mr-2 h-5 w-5" aria-hidden />
              {t("common.analytics")}
            </HoverPrefetchLink>
          </Button>
        </>
      }
    />
  );
}
