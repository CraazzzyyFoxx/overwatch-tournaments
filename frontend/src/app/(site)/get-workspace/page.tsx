import { Suspense, type ReactNode } from "react";
import type { Metadata } from "next";
import { getNow, getTranslations } from "next-intl/server";
import { CodeXml, KeyRound, User, type LucideIcon } from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import { LEDE_CLASS, SectionStack } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";
import { cn } from "@/lib/utils";
import { ClosingCta } from "./_components/ClosingCta";
import { CommunityProof, CommunityProofSkeleton } from "./_components/CommunityProof";
import { CreateForm } from "./_components/CreateForm";
import { DomainsSection, DomainsSkeleton } from "./_components/DomainsSection";
import { FeatureTour } from "./_components/FeatureTour";
import { HeroSteps } from "./_components/HeroSteps";
import { OrganizerFaq } from "./_components/OrganizerFaq";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "getWorkspace.metaTitle",
    descriptionKey: "getWorkspace.metaDescription",
    image: "/get-workspace/og"
  });
}

/** The home hero's dot field, behind the preview window and fading out toward the copy. */
const DOT_FIELD_CLASS =
  "pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(color-mix(in_srgb,var(--aqt-fg)_7%,transparent)_1px,transparent_1.5px)] bg-[length:22px_22px] [mask-image:radial-gradient(60%_70%_at_78%_50%,var(--aqt-bg),transparent_75%)]";

/**
 * The organizer page: what the platform gives a community and the form that
 * creates one (mock `OWT Get Workspace.html`).
 *
 * The community row and the domains section read the API, so each sits behind
 * its own Suspense boundary; everything else is static copy.
 */
export default async function GetWorkspacePage() {
  const [t, now] = await Promise.all([getTranslations("getWorkspace"), getNow()]);

  return (
    <SectionStack className="mx-auto w-full max-w-7xl gap-[clamp(56px,7vw,96px)] pt-5">
      <HeroFrame
        // Same quieter glow as the home hero.
        tint="color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
        className="bg-[linear-gradient(135deg,var(--aqt-bg-2),var(--aqt-bg))]"
      >
        <div className="relative px-[clamp(20px,3.2vw,40px)] py-[clamp(24px,3.2vw,40px)]">
          <span aria-hidden className={DOT_FIELD_CLASS} />
          <CreateForm
            year={now.getFullYear()}
            steps={
              <HeroSteps
                label={t("hero.stepsLabel")}
                steps={[
                  { title: t("hero.steps.create.title"), text: t("hero.steps.create.text") },
                  { title: t("hero.steps.discord.title"), text: t("hero.steps.discord.text") },
                  { title: t("hero.steps.verify.title"), text: t("hero.steps.verify.text") }
                ]}
              />
            }
          >
            <Eyebrow as="p">{t("hero.eyebrow")}</Eyebrow>
            <h1
              id="gw-title"
              className="mt-3 text-balance font-display text-display font-bold text-[color:var(--aqt-fg)]"
            >
              {t.rich("hero.title", {
                accent: (chunks) => <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
              })}
            </h1>
            <p className={cn(LEDE_CLASS, "mt-3")}>{t("hero.lede")}</p>
          </CreateForm>
        </div>
      </HeroFrame>

      <Suspense fallback={<CommunityProofSkeleton />}>
        <CommunityProof />
      </Suspense>

      <FeatureTour />

      <Suspense fallback={<DomainsSkeleton />}>
        <DomainsSection />
      </Suspense>

      <div className="grid grid-cols-1 gap-x-10 gap-y-6 border-t border-[color:var(--aqt-border)] pt-6 min-[900px]:grid-cols-3">
        <PlatformFact icon={KeyRound}>{t.rich("facts.auth", { b: bold })}</PlatformFact>
        <PlatformFact icon={User}>{t.rich("facts.profile", { b: bold })}</PlatformFact>
        <PlatformFact icon={CodeXml}>{t.rich("facts.api", { b: bold })}</PlatformFact>
      </div>

      <OrganizerFaq />

      <ClosingCta />
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
