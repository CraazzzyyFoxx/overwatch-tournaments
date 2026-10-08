import { Suspense, type ReactNode } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import {
  ChartColumn,
  ClipboardList,
  CodeXml,
  KeyRound,
  Network,
  Scale,
  ShieldCheck,
  Shuffle,
  User,
  Users,
  type LucideIcon
} from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import {
  EYEBROW_CLASS,
  HERO_TITLE_SIZE_CLASS,
  LEDE_CLASS,
  MoreLink,
  Section,
  SectionHead,
  SectionStack,
  SECTION_TITLE_CLASS,
  Showcase
} from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";
import { cn } from "@/lib/utils";
import { CreateForm } from "./_components/CreateForm";
import { DomainsSection, DomainsSkeleton } from "./_components/DomainsSection";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "getWorkspace.metaTitle",
    descriptionKey: "getWorkspace.metaDescription"
  });
}

const HERO_PADDING = "px-[clamp(24px,3.2vw,44px)] py-[clamp(24px,3.2vw,44px)]";

/**
 * The organizer page: what the platform gives a community and the form that
 * creates one (mock `OWT Get Workspace.html`).
 *
 * Only the domains section reads the API — it walks a real community's path
 * from platform page to custom domain — so it is the only one behind a
 * Suspense boundary.
 */
export default async function GetWorkspacePage() {
  const t = await getTranslations("getWorkspace");

  return (
    <SectionStack className="pt-5">
      <HeroFrame>
        <div
          className={cn(
            "grid grid-cols-1 gap-x-14 gap-y-8 min-[1024px]:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]",
            HERO_PADDING
          )}
        >
          <div className="min-w-0">
            <p className={EYEBROW_CLASS}>{t("hero.eyebrow")}</p>
            <h1
              id="gw-title"
              className={cn(
                "mt-3.5 max-w-[14em] text-balance font-display font-semibold leading-[1.03] tracking-[-0.01em] text-[color:var(--aqt-fg)]",
                HERO_TITLE_SIZE_CLASS
              )}
            >
              {t.rich("hero.title", {
                accent: (chunks) => (
                  <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
                )
              })}
            </h1>
            <p className={cn(LEDE_CLASS, "mt-3.5")}>{t("hero.lede")}</p>
            <CreateForm />
          </div>
          <ol
            aria-label={t("hero.stepsLabel")}
            className={cn(
              "grid content-start border-[color:var(--aqt-border)]",
              "min-[1024px]:border-l min-[1024px]:pl-10",
              "max-[1023px]:border-t max-[1023px]:pt-6"
            )}
          >
            {[
              { n: "01", title: t("hero.steps.create.title"), text: t("hero.steps.create.text") },
              { n: "02", title: t("hero.steps.discord.title"), text: t("hero.steps.discord.text") },
              { n: "03", title: t("hero.steps.verify.title"), text: t("hero.steps.verify.text") }
            ].map((step) => (
              <li
                key={step.n}
                className="grid grid-cols-[32px_minmax(0,1fr)] gap-x-3 gap-y-1 border-b border-[color:var(--aqt-border)] py-4 first:pt-0 last:border-b-0"
              >
                <span className="row-span-2 font-[family-name:var(--aqt-data)] text-label font-bold leading-normal tabular-nums text-[color:var(--aqt-teal)]">
                  {step.n}
                </span>
                <b className="font-display text-ui font-bold leading-[1.3] text-[color:var(--aqt-fg)]">
                  {step.title}
                </b>
                <p className="text-body text-[color:var(--aqt-fg-muted)]">{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </HeroFrame>

      <Section labelledBy="gw-feat-title">
        <SectionHead
          rubric={t("features.rubric")}
          title={t("features.title")}
          titleId="gw-feat-title"
          aside={<MoreLink href="/docs">{t("features.docs")}</MoreLink>}
        />
        <Showcase
          title={t("features.shots.form.title")}
          text={t("features.shots.form.text")}
          img="admin-form.webp"
          ratio="16 / 9"
          alt={t("features.shots.form.alt")}
        />
        <Showcase
          title={t("features.shots.registration.title")}
          text={t("features.shots.registration.text")}
          img="registration.webp"
          alt={t("features.shots.registration.alt")}
        />
        <Showcase
          title={t("features.shots.entries.title")}
          text={t("features.shots.entries.text")}
          img="admin-registrations.webp"
          alt={t("features.shots.entries.alt")}
        />
        <Showcase
          title={t("features.shots.stages.title")}
          text={t("features.shots.stages.text")}
          img="admin-bracket.webp"
          ratio="4 / 3"
          alt={t("features.shots.stages.alt")}
        />
        <Showcase
          title={t("features.shots.bracket.title")}
          text={t("features.shots.bracket.text")}
          img="bracket.webp"
          alt={t("features.shots.bracket.alt")}
        />
        <Showcase
          title={t("features.shots.mapStats.title")}
          text={t("features.shots.mapStats.text")}
          img="map-stats.webp"
          alt={t("features.shots.mapStats.alt")}
        />
        <ul className="mt-[clamp(56px,7vw,96px)] grid grid-cols-1 gap-x-8 gap-y-7 sm:grid-cols-2 min-[1280px]:grid-cols-4">
          {(
            [
              ["registration", ClipboardList, "/docs/organizers/registration"],
              ["balancer", Scale, "/docs/organizers/team-formation"],
              ["draft", Users, "/docs/organizers/draft"],
              ["brackets", Network, "/docs/organizers/brackets"],
              ["mixes", Shuffle, "/docs/organizers/mixes"],
              ["matchStats", ChartColumn, "/docs/organizers/logs"],
              ["roles", ShieldCheck, "/docs/organizers/roles"],
              ["api", CodeXml, "/docs/dev/api"]
            ] as const
          ).map(([key, Icon, href]) => (
            <li key={key} className="min-w-0">
              <Link
                href={href}
                prefetch={false}
                className="flex h-full flex-col gap-2 border-t border-[color:var(--aqt-border-3)] pt-[18px] transition-colors duration-150 hover:border-t-[color:var(--aqt-teal)] focus-visible:outline-offset-4"
              >
                <Icon className="size-5 text-[color:var(--aqt-teal)]" aria-hidden />
                <b className="font-display text-heading font-bold leading-[1.3] text-[color:var(--aqt-fg)]">
                  {t(`features.grid.${key}.title` as "features.grid.registration.title")}
                </b>
                <p className="text-body text-[color:var(--aqt-fg-muted)]">
                  {t(`features.grid.${key}.text` as "features.grid.registration.text")}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </Section>

      <Suspense fallback={<DomainsSkeleton />}>
        <DomainsSection />
      </Suspense>

      <div className="grid grid-cols-1 gap-x-10 gap-y-6 border-t border-[color:var(--aqt-border)] pt-6 min-[900px]:grid-cols-3">
        <PlatformFact icon={KeyRound}>{t.rich("facts.auth", { b: bold })}</PlatformFact>
        <PlatformFact icon={User}>{t.rich("facts.profile", { b: bold })}</PlatformFact>
        <PlatformFact icon={CodeXml}>{t.rich("facts.api", { b: bold })}</PlatformFact>
      </div>

      <HeroFrame>
        <div
          className={cn(
            "grid grid-cols-1 items-center gap-x-10 gap-y-5 md:grid-cols-[minmax(0,1fr)_auto]",
            "px-[clamp(24px,3.2vw,44px)] py-[clamp(24px,3vw,36px)]"
          )}
        >
          <div>
            <h2 id="gw-cta-title" className={SECTION_TITLE_CLASS}>
              {t("cta.title")}
            </h2>
            <p className={cn(LEDE_CLASS, "mt-2")}>{t("cta.lede")}</p>
          </div>
          <Link
            href="#create"
            className={owtButton({
              variant: "primary",
              size: "lg",
              className: "max-md:justify-self-start"
            })}
          >
            {t("cta.button")}
          </Link>
        </div>
      </HeroFrame>
    </SectionStack>
  );
}

const bold = (chunks: ReactNode) => (
  <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
);

function PlatformFact({
  icon: Icon,
  children
}: Readonly<{ icon: LucideIcon; children: ReactNode }>) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-[3px] size-4 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
      <p className="text-body text-[color:var(--aqt-fg-muted)]">{children}</p>
    </div>
  );
}
