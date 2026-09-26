import Image from "next/image";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ArrowRight, Home, Swords, Trophy, Users } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const QUICK_LINKS: { href: string; key: "tournaments" | "players" | "encounters"; icon: LucideIcon }[] =
  [
    { href: "/tournaments", key: "tournaments", icon: Trophy },
    { href: "/users", key: "players", icon: Users },
    { href: "/encounters", key: "encounters", icon: Swords }
  ];

/**
 * The 404 page body. Rendered by two boundaries: `app/not-found.tsx` for URLs
 * that match no route at all, and `app/(site)/not-found.tsx` for a `notFound()`
 * thrown by a site page (a missing player, tournament, …) — the latter keeps
 * the site header and footer, which the root boundary cannot.
 */
export async function NotFoundView() {
  const t = await getTranslations();

  return (
    <div className="flex flex-1 items-center py-4 md:py-8">
      <section className="liquid-glass relative isolate w-full overflow-hidden rounded-[32px] border border-[color:var(--aqt-border)] px-6 py-8 sm:px-8 sm:py-10 lg:px-12 lg:py-12">
        <div
          aria-hidden
          className="absolute right-5 top-5 text-[4rem] font-black leading-none tracking-[-0.08em] text-[color:var(--aqt-fg)]/5 sm:text-[5.5rem] lg:text-[7rem]"
        >
          404
        </div>

        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr),24rem] lg:items-start lg:gap-10 xl:grid-cols-[minmax(0,1fr),27rem]">
          <div className="max-w-2xl pt-2">
            <p className="aqt-tnum text-label font-semibold uppercase tracking-[0.32em] text-[color:var(--aqt-fg-faint)]">
              {t("notFound.eyebrow")}
            </p>

            <h1 className="mt-4 max-w-xl font-onest text-4xl font-semibold tracking-[-0.04em] text-[color:var(--aqt-fg)] sm:text-5xl lg:text-6xl">
              {t("notFound.title")}
            </h1>

            {/* One explanation, stated once. The old page repeated the same
                "moved, expired, or never existed" sentence three times. */}
            <p className="mt-5 max-w-prose text-base leading-7 text-[color:var(--aqt-fg-muted)]">
              {t("notFound.description")}
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg" className="rounded-full px-6">
                <Link href="/">
                  <Home className="size-4" aria-hidden />
                  {t("notFound.backHome")}
                </Link>
              </Button>

              <Button asChild size="lg" variant="outline" className="rounded-full px-6">
                <Link href="/tournaments">
                  <Trophy className="size-4" aria-hidden />
                  {t("notFound.browseTournaments")}
                </Link>
              </Button>
            </div>
          </div>

          <div className="space-y-4 lg:w-full lg:justify-self-end">
            <Card className="liquid-glass-panel relative overflow-hidden p-3">
              <div className="relative aspect-[5/4] overflow-hidden rounded-[24px] border border-[color:var(--aqt-border)]">
                <Image
                  src="/not-found.avif"
                  alt=""
                  fill
                  sizes="(min-width: 1280px) 27rem, (min-width: 1024px) 24rem, 100vw"
                  className="object-cover opacity-70"
                />
              </div>
            </Card>

            <Card className="liquid-glass-panel p-4 sm:p-5">
              <p className="px-1 aqt-tnum text-label uppercase tracking-[0.32em] text-[color:var(--aqt-fg-dim)]">
                {t("notFound.quickRecovery")}
              </p>

              <div className="mt-4 grid gap-3">
                {QUICK_LINKS.map(({ href, key, icon: Icon }) => (
                  <Link
                    key={href}
                    href={href}
                    className="group flex items-center gap-4 rounded-[22px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 outline-none transition-colors duration-200 hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  >
                    <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg)]">
                      <Icon className="size-4" aria-hidden />
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-[color:var(--aqt-fg)]">
                        {t(`notFound.links.${key}.title`)}
                      </span>
                      <span className="mt-1 block text-sm leading-6 text-[color:var(--aqt-fg-muted)]">
                        {t(`notFound.links.${key}.description`)}
                      </span>
                    </span>

                    <ArrowRight
                      aria-hidden
                      className="size-4 shrink-0 text-[color:var(--aqt-fg-dim)] transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
                    />
                  </Link>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </section>
    </div>
  );
}
