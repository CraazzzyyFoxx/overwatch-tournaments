"use client";

import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Check, Clock, Lock } from "lucide-react";

import { MoreLink, SECTION_TITLE_CLASS } from "@/components/site/open-layout";
import {
  AutoplayButton,
  AutoplayRail,
  RAIL_LIST_CLASS,
  RAIL_TAB_CLASS
} from "@/components/site/OrganizerTabs";
import { owtButton } from "@/components/site/owt-button";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { useAutoplay } from "@/hooks/useAutoplay";
import { useOffscreen } from "@/hooks/useOffscreen";
import { cn } from "@/lib/utils";

/** The real community the section walks through, resolved from the directory. */
export type DomainExample = {
  workspace: { id: number; name: string; icon_url: string | null };
  slug: string;
  subdomain: string;
  customDomain: string;
  /** `deriveWorkspacePalette` output, scoped to the preview from step 2 on. */
  palette: Record<string, string>;
  swatches: { key: string; color: string }[];
  tournaments: number | null;
  players: number | null;
  /** Year of its first tournament, as four digits. */
  firstYear: string | null;
};

/** How long each step holds the preview. */
const INTERVAL_MS = 5000;

const STEPS = ["platform", "subdomain", "verify", "cname"] as const;

/** The docs article that connects a subdomain and a domain. */
const DOCS_HREF = "/docs/organizers/workspace";

const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";

const DNS_ROW =
  "grid items-center gap-3 rounded-lg px-2.5 py-2.5 font-mono text-caption transition-colors duration-300 " +
  "grid-cols-[52px_minmax(0,1fr)] sm:grid-cols-[64px_minmax(0,1.3fr)_minmax(0,1fr)_132px]";

const PILL =
  "inline-flex items-center gap-1.5 justify-self-start whitespace-nowrap rounded-full border px-[9px] py-[3px] " +
  "font-[family-name:var(--aqt-data)] text-label font-bold uppercase tracking-label transition-colors duration-300 [&_svg]:size-3.5";

const PILL_OK =
  "border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_12%,transparent)] text-[color:var(--aqt-emerald)]";

const PILL_WAITING = "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-dim)]";

/** The window's glow (the tour window's, DESIGN.md §5 game polish): teal on the platform, the community's own accent once the site is branded. */
const WINDOW_CLASS =
  "overflow-hidden rounded-xl border border-[color:color-mix(in_srgb,var(--glow)_40%,transparent)] bg-[color:var(--aqt-bg)] " +
  "shadow-[0_0_0_1px_color-mix(in_srgb,var(--glow)_14%,transparent),0_0_80px_-18px_color-mix(in_srgb,var(--glow)_55%,transparent)] " +
  "transition-[border-color,box-shadow] duration-500 motion-reduce:transition-none";

/** One of the two site headers stacked in one cell; the step shows one and fades the other out. */
const SITE_HEADER =
  "col-start-1 row-start-1 flex min-w-0 items-center gap-3 px-4 transition-[opacity,visibility] duration-500 motion-reduce:transition-none";

/**
 * The custom-domain walk-through: the section head and four steps beside one
 * browser window showing a real community (Jaristo Squad when it has the
 * whole path) as each step leaves it — its platform page, its subdomain in its
 * own colours, then its own domain — with the DNS records whose status follows
 * the step. The steps turn by themselves every `INTERVAL_MS` like the tour's
 * tabs (`useAutoplay`: held off screen, under the pointer or focus, a pause
 * button, stopped under reduced motion). Without an example the steps read as
 * a plain list.
 */
export function DomainSteps({
  example,
  zone
}: Readonly<{ example: DomainExample | null; zone: string }>) {
  const t = useTranslations("getWorkspace.domains");

  // Literal keys, not `steps.${i}` — typed messages only resolve literals.
  const steps = [
    { title: t("steps.platform.title"), text: t("steps.platform.text") },
    { title: t("steps.subdomain.title"), text: t("steps.subdomain.text") },
    { title: t("steps.verify.title"), text: t("steps.verify.text") },
    { title: t("steps.cname.title"), text: t("steps.cname.text") }
  ];

  const head = (
    <>
      <h2 id="gw-dom-title" className={SECTION_TITLE_CLASS}>
        {t("title")}
      </h2>
      <p className="mt-1.5 text-body text-[color:var(--aqt-fg-dim)]">{t("sub")}</p>
    </>
  );

  if (!example) {
    return (
      <div>
        {head}
        <ol className="mt-5 grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map(({ title, text }, step) => (
            <li key={title} className="flex gap-3 border-t border-[color:var(--aqt-border)] pt-4">
              <span className={cn(eyebrowClass(), "pt-[3px] tabular-nums")} aria-hidden>
                0{step + 1}
              </span>
              <span className="grid gap-1">
                <b className="font-display text-ui font-semibold text-[color:var(--aqt-fg)]">{title}</b>
                <span className="text-body text-[color:var(--aqt-fg-muted)]">{text}</span>
              </span>
            </li>
          ))}
        </ol>
        <MoreLink href={DOCS_HREF} className="mt-4">
          {t("docs")}
        </MoreLink>
      </div>
    );
  }

  return (
    <Stepper example={example} zone={zone} steps={steps}>
      {head}
    </Stepper>
  );
}

function Stepper({
  example,
  zone,
  steps,
  children
}: Readonly<{
  example: DomainExample;
  zone: string;
  steps: { title: string; text: string }[];
  children: ReactNode;
}>) {
  const t = useTranslations("getWorkspace.domains");
  const labelId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const urlRef = useRef<HTMLSpanElement>(null);
  const { index, select, playing, autoplay, toggle, holdProps } = useAutoplay(
    STEPS.length,
    INTERVAL_MS,
    useOffscreen(ref)
  );

  const url = (step: number) => {
    if (step === 0) return `${zone}/workspace/${example.slug}`;
    if (step === 3) return example.customDomain;
    return `${example.subdomain}.${zone}`;
  };

  // The address bar's new address rises in when it changes (Web Animations: a
  // class would not replay); reduced motion swaps it in place.
  const shown = useRef(index);
  useEffect(() => {
    const from = shown.current;
    shown.current = index;
    if (url(from) === url(index) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    urlRef.current?.animate(
      [
        { opacity: 0, transform: "translateY(6px)" },
        { opacity: 1, transform: "none" }
      ],
      { duration: 380, easing: EASE }
    );
    // `url` reads props that never change between steps; the effect follows the step alone.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const address = (step: number): ReactNode => {
    const em = (text: string) => <em className="not-italic text-[color:var(--aqt-fg)]">{text}</em>;
    if (step === 0)
      return (
        <>
          {zone}/workspace/{em(example.slug)}
        </>
      );
    if (step === 1)
      return (
        <>
          {em(example.subdomain)}.{zone}
        </>
      );
    if (step === 2) return <>TXT {em(`_owt-verify.${example.customDomain}`)}</>;
    return (
      <>
        CNAME {em(example.customDomain)} → {zone}
      </>
    );
  };

  const own = index > 0;
  const brandAccent = example.palette["--aqt-teal"] ?? "var(--aqt-teal)";
  const nav = (
    <span className="flex gap-0.5 text-label text-[color:var(--aqt-fg-muted)]">
      <span className="rounded-md bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] px-2 py-1.5 text-[color:var(--aqt-teal)]">
        {t("preview.navTournaments")}
      </span>
      <span className="rounded-md px-2 py-1.5">{t("preview.navPlayers")}</span>
      <span className="rounded-md px-2 py-1.5 max-sm:hidden">{t("preview.navStats")}</span>
    </span>
  );

  return (
    <Tabs
      ref={ref}
      value={STEPS[index]}
      onValueChange={(value) => select(STEPS.indexOf(value as (typeof STEPS)[number]))}
      orientation="vertical"
      className="grid grid-cols-[minmax(0,1fr)] items-start gap-x-[clamp(24px,4vw,56px)] gap-y-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]"
    >
      <div>
        {children}
        <div className="mt-6 flex items-center justify-between gap-3">
          <Eyebrow id={labelId}>{t("stepsLabel")}</Eyebrow>
          <AutoplayButton autoplay={autoplay} onToggle={toggle} labels={{ pause: t("pause"), play: t("play") }} />
        </div>
        <TabsList variant="rail" aria-labelledby={labelId} className={cn("mt-2.5", RAIL_LIST_CLASS)} {...holdProps}>
          {steps.map(({ title, text }, step) => (
            <TabsTrigger key={STEPS[step]} value={STEPS[step]} className={RAIL_TAB_CLASS}>
              {step === index ? <AutoplayRail running={playing} ms={INTERVAL_MS} /> : null}
              <span
                aria-hidden
                className="pt-[3px] font-[family-name:var(--aqt-data)] text-label font-semibold tabular-nums tracking-label text-[color:var(--aqt-fg-faint)] transition-colors group-data-[state=active]:text-[color:var(--aqt-teal)]"
              >
                0{step + 1}
              </span>
              <span className="grid min-w-0 gap-0.5">
                <span className="font-display text-heading font-semibold">{title}</span>
                <code className="font-mono text-caption font-normal leading-[1.4] text-[color:var(--aqt-fg-dim)] [overflow-wrap:anywhere]">
                  {address(step)}
                </code>
                <span className="text-body font-normal text-[color:var(--aqt-fg-muted)]">{text}</span>
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
        <MoreLink href={DOCS_HREF} className="mt-4">
          {t("docs")}
        </MoreLink>
      </div>

      <TabsContent value={STEPS[index]} {...holdProps}>
        {/* The browser is an illustration: each step's text carries the facts, the DNS table below reads out. */}
        <div aria-hidden style={{ "--glow": own ? brandAccent : "var(--aqt-teal)" } as CSSProperties}>
          <div className={WINDOW_CLASS}>
            <div className="flex h-10 items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3.5">
              <span className="flex gap-1.5">
                {[0, 1, 2].map((dot) => (
                  <i key={dot} className="size-[9px] rounded-full bg-[color:var(--aqt-border-3)]" />
                ))}
              </span>
              <span className="flex h-[26px] min-w-0 flex-1 items-center gap-2 overflow-hidden whitespace-nowrap rounded-full bg-[color:var(--aqt-overlay-3)] px-2.5 font-mono text-label leading-none text-[color:var(--aqt-fg-muted)]">
                <Lock className="size-3.5 shrink-0" aria-hidden />
                <span ref={urlRef} className="truncate">
                  {url(index)}
                </span>
              </span>
            </div>
            <div
              className="bg-[color:var(--aqt-bg)] text-[color:var(--aqt-fg)] transition-colors duration-500 motion-reduce:transition-none [&_*]:transition-colors [&_*]:duration-500 motion-reduce:[&_*]:transition-none"
              style={own ? (example.palette as CSSProperties) : undefined}
            >
              <div className="grid h-12 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
                <div className={cn(SITE_HEADER, own && "invisible opacity-0")}>
                  <Image src="/brand-mark.svg" alt="" width={22} height={22} />
                  <b className="font-display text-body font-extrabold leading-none">OWT</b>
                  <WorkspaceAvatar workspace={example.workspace} size={20} className="max-sm:hidden" />
                  <span className="truncate text-label text-[color:var(--aqt-fg-muted)] max-sm:hidden">
                    {example.workspace.name}
                  </span>
                  <span className="ml-auto">{nav}</span>
                </div>
                <div className={cn(SITE_HEADER, !own && "invisible opacity-0")}>
                  <WorkspaceAvatar workspace={example.workspace} size={22} />
                  <b className="truncate font-display text-body font-extrabold leading-none">{example.workspace.name}</b>
                  <span className="ml-2 max-sm:ml-auto">{nav}</span>
                </div>
              </div>
              <div className="relative grid gap-3 px-5 pb-6 pt-[22px]">
                <span className="absolute inset-x-0 top-0 h-0.5 bg-[color:var(--aqt-teal)]" />
                {example.firstYear ? <Eyebrow>{t("preview.since", { year: example.firstYear })}</Eyebrow> : null}
                <div className="flex items-center gap-3 font-display text-title font-semibold leading-[1.1]">
                  <WorkspaceAvatar workspace={example.workspace} size={40} />
                  {example.workspace.name}
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className={owtButton({ variant: "primary", size: "sm" })}>{t("preview.allTournaments")}</span>
                  <span className={owtButton({ variant: "outline", size: "sm" })}>{t("preview.stats")}</span>
                </div>
                <div className="flex justify-between gap-3 border-t border-[color:var(--aqt-border)] pt-2.5 text-label text-[color:var(--aqt-fg-dim)]">
                  <span>
                    {example.tournaments !== null && example.players !== null
                      ? t("preview.counts", { tournaments: example.tournaments, players: example.players })
                      : null}
                  </span>
                  <span className={cn("transition-opacity duration-500", !own && "invisible opacity-0")}>
                    {t.rich("preview.poweredBy", {
                      b: (chunks) => <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
                    })}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-2">
          <div
            aria-hidden
            className={cn(
              "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg px-2.5 py-2 transition-[background-color,opacity] duration-300",
              index === 0 && "opacity-45",
              index === 1 && "bg-[color:var(--aqt-overlay-3)]"
            )}
          >
            <Eyebrow>{t("preview.swatches")}</Eyebrow>
            <span className="flex gap-1.5">
              {example.swatches.map((swatch) => (
                <span
                  key={swatch.key}
                  title={`${swatch.key}: ${swatch.color}`}
                  className="size-[24px] rounded-[7px] border border-[color:var(--aqt-border-2)]"
                  style={{ background: swatch.color }}
                />
              ))}
            </span>
          </div>
          <Dns domain={example.customDomain} zone={zone} step={index} />
        </div>
      </TabsContent>
    </Tabs>
  );
}

/** The two records a custom domain needs; each one's status follows the step that settles it. */
function Dns({ domain, zone, step }: Readonly<{ domain: string; zone: string; step: number }>) {
  const t = useTranslations("getWorkspace.domains.preview");

  return (
    <div role="table" aria-label={t("dnsCaption", { domain })}>
      <div role="row" className={cn(DNS_ROW, eyebrowClass(), "py-1.5 leading-[1.25]")}>
        <span role="columnheader">{t("dnsType")}</span>
        <span role="columnheader">{t("dnsName")}</span>
        <span role="columnheader" className="max-sm:hidden">
          {t("dnsValue")}
        </span>
        <span role="columnheader" className="max-sm:hidden">
          {t("dnsStatus")}
        </span>
      </div>
      <div role="row" className={cn(DNS_ROW, step === 2 && "bg-[color:var(--aqt-overlay-3)]")}>
        <span role="cell">TXT</span>
        <span role="cell" className="[overflow-wrap:anywhere]">
          _owt-verify.{domain}
        </span>
        <span role="cell" className="text-[color:var(--aqt-fg-dim)] max-sm:col-start-2">
          owt-verify-…
        </span>
        <span role="cell" className="max-sm:col-start-2">
          <DnsStatus ok={step >= 2} label={step >= 2 ? t("dnsConfirmed") : t("dnsWaiting")} />
        </span>
      </div>
      <div role="row" className={cn(DNS_ROW, step === 3 && "bg-[color:var(--aqt-overlay-3)]")}>
        <span role="cell">CNAME</span>
        <span role="cell" className="[overflow-wrap:anywhere]">
          {domain}
        </span>
        <span role="cell" className="text-[color:var(--aqt-fg-dim)] max-sm:col-start-2">
          {zone}
        </span>
        <span role="cell" className="max-sm:col-start-2">
          <DnsStatus ok={step >= 3} label={step >= 3 ? t("dnsWorking") : t("dnsWaiting")} />
        </span>
      </div>
    </div>
  );
}

/** A record's status pill: settled (green, a check) or still waiting (a clock). */
function DnsStatus({ ok, label }: Readonly<{ ok: boolean; label: string }>) {
  return (
    <span className={cn(PILL, ok ? PILL_OK : PILL_WAITING)}>
      {ok ? <Check aria-hidden /> : <Clock aria-hidden />}
      {label}
    </span>
  );
}
