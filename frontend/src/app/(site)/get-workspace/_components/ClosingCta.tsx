"use client";

import { useState, type FormEvent } from "react";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroFrame } from "@/components/site/PageHero";
import { LEDE_CLASS, SECTION_TITLE_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import { suggestSlug } from "@/lib/workspace/slug";

import { handOffName } from "./create-handoff";

const TITLE_ID = "gw-cta-title";

/**
 * The organizer page's closing banner (mock C1): the organizer banner's frame
 * with a name field, the address it suggests under it. "Create community"
 * hands the name to the hero's form (`handOffName`), which fills it in, comes
 * into view and focuses its own button: the visitor neither scrolls back nor
 * types the name twice.
 */
export function ClosingCta() {
  const t = useTranslations("getWorkspace.cta");
  const create = useTranslations("getWorkspace.create");
  const [name, setName] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    handOffName(name);
  }

  return (
    <HeroFrame variant="plain">
      {/* The organizer banner's corner bloom. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(50%_140%_at_0%_100%,color-mix(in_srgb,var(--aqt-teal)_13%,transparent),transparent_70%)]"
      />
      <div className="grid grid-cols-[minmax(0,1fr)] items-center gap-x-12 gap-y-5 px-[clamp(20px,3vw,40px)] py-[clamp(24px,3vw,36px)] min-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,500px)]">
        <div>
          <h2 id={TITLE_ID} className={SECTION_TITLE_CLASS}>
            {t("title")}
          </h2>
          <p className={cn(LEDE_CLASS, "mt-2")}>{t("lede")}</p>
        </div>
        <form noValidate onSubmit={onSubmit} aria-labelledby={TITLE_ID}>
          <label htmlFor="gw-cta-name" className="mb-2 block text-body font-medium text-[color:var(--aqt-fg)]">
            {create("name")}
          </label>
          <div className="flex flex-col gap-2.5 sm:flex-row sm:items-start">
            <div className="min-w-0 flex-1">
              <Input
                id="gw-cta-name"
                name="name"
                variant="surface"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={create("namePlaceholder")}
                autoComplete="off"
                aria-describedby="gw-cta-address"
                className="h-11"
              />
              <p
                id="gw-cta-address"
                className="mt-2 font-mono text-caption leading-relaxed text-[color:var(--aqt-fg-dim)] [overflow-wrap:anywhere]"
              >
                {PLATFORM_ZONE}/workspace/
                <wbr />
                <span className="text-[color:var(--aqt-fg-muted)]">{suggestSlug(name)}</span>
              </p>
            </div>
            <Button
              type="submit"
              variant={null}
              size={null}
              className={owtButton({ variant: "primary", size: "lg" })}
            >
              {t("button")}
              <ArrowRight aria-hidden />
            </Button>
          </div>
        </form>
      </div>
    </HeroFrame>
  );
}
