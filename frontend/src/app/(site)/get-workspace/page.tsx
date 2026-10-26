import { Suspense, type ReactNode } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { CodeXml, KeyRound, Scale, ShieldCheck, Shuffle, User, Users, type LucideIcon } from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import {
  HERO_TITLE_SIZE_CLASS,
  LEDE_CLASS,
  MoreLink,
  Section,
  SectionHead,
  SectionStack,
  SECTION_TITLE_CLASS
} from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";
import { cn } from "@/lib/utils";
import { CommunityProof, CommunityProofSkeleton } from "./_components/CommunityProof";
import { CreateForm } from "./_components/CreateForm";
import { DomainsSection, DomainsSkeleton } from "./_components/DomainsSection";
import { FeatureTabs, type FeatureShot } from "./_components/FeatureTabs";
import { HeroSteps } from "./_components/HeroSteps";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "getWorkspace.metaTitle",
    descriptionKey: "getWorkspace.metaDescription",
    image: "/get-workspace/og"
  });
}

const HERO_PADDING = "px-[clamp(20px,3.2vw,40px)] py-[clamp(24px,3.2vw,40px)]";

/** The tour's tabs, in the order a tournament happens; `docs` sets each one up. */
const SHOTS = [
  { key: "form", img: "admin-form.webp", docs: "/docs/organizers/registration" },
  { key: "registration", img: "registration.webp", docs: "/docs/organizers/registration" },
  { key: "entries", img: "admin-registrations.webp", docs: "/docs/organizers/registration" },
  { key: "stages", img: "admin-bracket.webp", docs: "/docs/organizers/brackets" },
  { key: "bracket", img: "bracket.webp", docs: "/docs/organizers/brackets" },
  { key: "mapStats", img: "map-stats.webp", docs: "/docs/organizers/logs" }
] as const;

/** What the tour does not show, each with its docs article. */
const MORE_FEATURES = [
  ["balancer", Scale, "/docs/organizers/team-formation"],
  ["draft", Users, "/docs/organizers/draft"],
  ["mixes", Shuffle, "/docs/organizers/mixes"],
  ["roles", ShieldCheck, "/docs/organizers/roles"],
  ["api", CodeXml, "/docs/dev/api"]
] as const;

const FAQ = ["price", "verification", "discord"] as const;

/**
 * The organizer page: what the platform gives a community and the form that
 * creates one (mock `OWT Get Workspace.html`).
 *
 * The community row and the domains section read the API, so each sits behind
 * its own Suspense boundary; everything else is static copy.
 */
export default async function GetWorkspacePage() {
  const t = await getTranslations("getWorkspace");

  const shots: FeatureShot[] = SHOTS.map(({ key, img, docs }) => ({
    key,
    img,
    docs,
    title: t(`features.shots.${key}.title` as const),
    text: t(`features.shots.${key}.text` as const),
    alt: t(`features.shots.${key}.alt` as const)
  }));

  return (
    <SectionStack className="mx-auto w-full max-w-7xl gap-[clamp(56px,7vw,96px)] pt-5">
      <HeroFrame
        // Same quieter glow as the home hero.
        tint="color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
        className="bg-[linear-gradient(135deg,var(--aqt-bg-2),var(--aqt-bg))]"
      >
        <div
          className={cn(
            "grid grid-cols-1 gap-x-[clamp(24px,4vw,48px)] gap-y-8 min-[1024px]:grid-cols-[minmax(0,1.8fr)_minmax(260px,1fr)]",
            HERO_PADDING
          )}
        >
          <div className="min-w-0">
            <Eyebrow as="p">{t("hero.eyebrow")}</Eyebrow>
            <h1
              id="gw-title"
              className={cn(
                HERO_TITLE_SIZE_CLASS,
                "mt-3 max-w-[18em] text-balance font-display font-semibold leading-[1.08] tracking-[-0.02em] text-[color:var(--aqt-fg)]"
              )}
            >
              {t.rich("hero.title", {
                accent: (chunks) => (
                  <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
                )
              })}
            </h1>
            <p className={cn(LEDE_CLASS, "mt-3 max-w-[38rem]")}>{t("hero.lede")}</p>
            <CreateForm />
          </div>
          <HeroSteps
            label={t("hero.stepsLabel")}
            steps={[
              { title: t("hero.steps.create.title"), text: t("hero.steps.create.text") },
              { title: t("hero.steps.discord.title"), text: t("hero.steps.discord.text") },
              { title: t("hero.steps.verify.title"), text: t("hero.steps.verify.text") }
            ]}
            className="max-[1023px]:border-t max-[1023px]:border-[color:var(--aqt-border)] max-[1023px]:pt-6"
          />
        </div>
      </HeroFrame>

      <Suspense fallback={<CommunityProofSkeleton />}>
        <CommunityProof />
      </Suspense>

      <Section labelledBy="gw-feat-title">
        <SectionHead
          title={t("features.title")}
          titleId="gw-feat-title"
          aside={<MoreLink href="/docs">{t("features.docs")}</MoreLink>}
        />
        <FeatureTabs shots={shots} labelledBy="gw-feat-title" docsLabel={t("features.howTo")} />
        <ul className="mt-[clamp(56px,7vw,96px)] grid grid-cols-1 gap-x-8 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 min-[1280px]:grid-cols-5">
          {MORE_FEATURES.map(([key, Icon, href]) => (
            <li key={key} className="min-w-0">
              <Link
                href={href}
                prefetch={false}
                className="flex h-full flex-col gap-2.5 border-t border-[color:var(--aqt-border)] pt-5 transition-colors duration-150 hover:border-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[color:var(--aqt-teal)]"
              >
                <Icon className="size-5 text-[color:var(--aqt-teal)]" aria-hidden />
                <b className="font-display text-heading font-semibold leading-[1.3] text-[color:var(--aqt-fg)]">
                  {t(`features.grid.${key}.title` as const)}
                </b>
                <p className="text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
                  {t(`features.grid.${key}.text` as const)}
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

      <Section labelledBy="gw-faq-title">
        <SectionHead title={t("faq.title")} titleId="gw-faq-title" />
        <dl className="max-w-[65ch] divide-y divide-[color:var(--aqt-border)]">
          {FAQ.map((key) => (
            <div key={key} className="py-5 first:pt-1">
              <dt className="font-display text-heading font-semibold leading-[1.3] text-[color:var(--aqt-fg)]">
                {t(`faq.${key}.q` as const)}
              </dt>
              <dd className="mt-2 text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
                {t(`faq.${key}.a` as const)}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <HeroFrame variant="plain">
        <div
          className={cn(
            "grid grid-cols-1 items-center gap-x-10 gap-y-5 md:grid-cols-[minmax(0,1fr)_auto]",
            "px-[clamp(20px,3vw,40px)] py-[clamp(24px,3vw,36px)]"
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
