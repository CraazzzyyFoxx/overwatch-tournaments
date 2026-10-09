"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Check, Clock, Lock } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { cn } from "@/lib/utils";
import styles from "./domains.module.css";

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

const DNS_ROW =
  "grid items-center gap-3 py-2.5 font-mono text-caption " +
  "grid-cols-[52px_minmax(0,1fr)] sm:grid-cols-[64px_minmax(0,1.3fr)_minmax(0,1fr)_156px]";

const OK_PILL =
  "inline-flex items-center gap-1.5 justify-self-start whitespace-nowrap rounded-full border px-[9px] py-[3px] " +
  "font-[family-name:var(--aqt-data)] text-label font-bold uppercase tracking-label";

/**
 * The four domain steps with the sticky preview (mock `.dom`).
 *
 * The step crossing the middle of the viewport is the current one: it lights
 * up, the teal rule slides to it and the sticky stage cross-fades to its
 * preview. Below 1024px the stage is gone and each step carries its own
 * preview. The previews are an illustration (`aria-hidden`); each step's text
 * carries the facts.
 */
export function DomainSteps({
  example,
  zone
}: Readonly<{ example: DomainExample | null; zone: string }>) {
  const t = useTranslations("getWorkspace.domains");
  const listRef = useRef<HTMLOListElement>(null);
  const currentRef = useRef(0);
  const [current, setCurrent] = useState(0);
  const [barY, setBarY] = useState(0);

  // Literal keys, not `steps.${i}` — typed messages only resolve literals.
  const steps = [
    { title: t("steps.platform.title"), text: t("steps.platform.text") },
    { title: t("steps.subdomain.title"), text: t("steps.subdomain.text") },
    { title: t("steps.verify.title"), text: t("steps.verify.text") },
    { title: t("steps.cname.title"), text: t("steps.cname.text") }
  ];

  const place = useCallback(() => {
    const step = listRef.current?.querySelector<HTMLElement>(`[data-dstep="${currentRef.current}"]`);
    setBarY(step?.offsetTop ?? 0);
  }, []);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const stepEls = [...list.querySelectorAll<HTMLElement>("[data-dstep]")];
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          currentRef.current = Number((entry.target as HTMLElement).dataset.dstep);
          setCurrent(currentRef.current);
          place();
        }
      },
      { rootMargin: "-49% 0px -50% 0px" }
    );
    stepEls.forEach((step) => observer.observe(step));
    // Step heights change with width and with font load.
    const resize = new ResizeObserver(place);
    resize.observe(list);
    return () => {
      observer.disconnect();
      resize.disconnect();
    };
  }, [place]);

  const url = (step: number) => {
    if (!example) return "";
    if (step === 0) return `${zone}/workspace/${example.slug}`;
    if (step === 3) return example.customDomain;
    return `${example.subdomain}.${zone}`;
  };

  const address = (step: number): ReactNode => {
    if (!example) return null;
    if (step === 0)
      return (
        <>
          {zone}/workspace/<em className="not-italic text-[color:var(--aqt-fg)]">{example.slug}</em>
        </>
      );
    if (step === 1)
      return (
        <>
          <em className="not-italic text-[color:var(--aqt-fg)]">{example.subdomain}</em>.{zone}
        </>
      );
    if (step === 2)
      return (
        <>
          TXT{" "}
          <em className="not-italic text-[color:var(--aqt-fg)]">
            _owt-verify.{example.customDomain}
          </em>
        </>
      );
    return (
      <>
        CNAME <em className="not-italic text-[color:var(--aqt-fg)]">{example.customDomain}</em> →{" "}
        {zone}
      </>
    );
  };

  const preview = (step: number) => {
    if (!example) return null;
    const own = step > 0;
    const below =
      step === 1 ? (
        <Swatches example={example} label={t("preview.swatches")} />
      ) : step >= 2 ? (
        <Dns
          domain={example.customDomain}
          zone={zone}
          cnameOk={step === 3}
          labels={{
            caption: t("preview.dnsCaption", { domain: example.customDomain }),
            type: t("preview.dnsType"),
            name: t("preview.dnsName"),
            value: t("preview.dnsValue"),
            status: t("preview.dnsStatus"),
            confirmed: t("preview.dnsConfirmed"),
            working: t("preview.dnsWorking"),
            waiting: t("preview.dnsWaiting")
          }}
        />
      ) : null;

    return (
      <>
        <div className="overflow-hidden rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg)] shadow-[0_18px_50px_rgb(0_0_0/0.45)]">
          <div className="flex h-10 items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3.5">
            <span className="flex gap-1.5">
              <i className="size-[9px] rounded-full bg-[color:var(--aqt-border-3)]" />
              <i className="size-[9px] rounded-full bg-[color:var(--aqt-border-3)]" />
              <i className="size-[9px] rounded-full bg-[color:var(--aqt-border-3)]" />
            </span>
            <span className="flex h-[26px] min-w-0 flex-1 items-center gap-2 overflow-hidden whitespace-nowrap rounded-full bg-[color:var(--aqt-overlay-3)] px-2.5 font-mono text-[12px] leading-none text-[color:var(--aqt-fg-muted)]">
              <Lock className="size-3.5 shrink-0" aria-hidden />
              {url(step)}
            </span>
          </div>
          <div
            className="bg-[color:var(--aqt-bg)] text-[color:var(--aqt-fg)]"
            style={own ? (example.palette as CSSProperties) : undefined}
          >
            <div className="flex h-12 items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4">
              {own ? (
                <>
                  <WorkspaceAvatar workspace={example.workspace} size={22} />
                  <b className="font-display text-[14px] font-extrabold leading-none">
                    {example.workspace.name}
                  </b>
                </>
              ) : (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element -- static brand mark */}
                  <img src="/brand-mark.svg" alt="" width={22} height={22} />
                  <b className="font-display text-[14px] font-extrabold leading-none">OWT</b>
                  <WorkspaceAvatar workspace={example.workspace} size={20} />
                  <span className="text-label text-[color:var(--aqt-fg-muted)]">
                    {example.workspace.name}
                  </span>
                </>
              )}
              <span
                className={cn(
                  "flex gap-0.5 text-label text-[color:var(--aqt-fg-muted)]",
                  own ? "ml-2" : "ml-auto"
                )}
              >
                <span className="rounded-md bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] px-2 py-1.5 text-[color:var(--aqt-teal)]">
                  {t("preview.navTournaments")}
                </span>
                <span className="rounded-md px-2 py-1.5">{t("preview.navPlayers")}</span>
                <span className="rounded-md px-2 py-1.5">{t("preview.navStats")}</span>
              </span>
            </div>
            <div className="relative grid gap-3 px-5 pb-6 pt-[22px]">
              <span
                aria-hidden
                className="absolute inset-x-0 top-0 h-0.5 bg-[color:var(--aqt-teal)]"
              />
              {example.firstYear ? (
                <span className={EYEBROW_CLASS}>
                  {t("preview.since", { year: example.firstYear })}
                </span>
              ) : null}
              <div className="flex items-center gap-3 font-display text-[26px] font-semibold leading-[1.1]">
                <WorkspaceAvatar workspace={example.workspace} size={40} />
                {example.workspace.name}
              </div>
              <div className="flex flex-wrap gap-2">
                <span className={owtButton({ variant: "primary", size: "sm" })}>
                  {t("preview.allTournaments")}
                </span>
                <span className={owtButton({ variant: "outline", size: "sm" })}>
                  {t("preview.stats")}
                </span>
              </div>
              <div className="flex justify-between gap-3 border-t border-[color:var(--aqt-border)] pt-2.5 text-label text-[color:var(--aqt-fg-dim)]">
                <span>
                  {example.tournaments !== null && example.players !== null
                    ? t("preview.counts", {
                        tournaments: example.tournaments,
                        players: example.players
                      })
                    : null}
                </span>
                {own ? (
                  <span>
                    {t.rich("preview.poweredBy", {
                      b: (chunks) => (
                        <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
                      )
                    })}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>
        {below ? <div className="mt-3.5">{below}</div> : null}
      </>
    );
  };

  return (
    <div className={cn(styles.dom, !example && styles.textOnly)}>
      <ol
        ref={listRef}
        className={styles.steps}
        style={{ "--bar-y": `${barY}px` } as CSSProperties}
      >
        {steps.map(({ title, text }, step) => (
          <li
            key={step}
            data-dstep={step}
            className={cn(styles.step, step === current && styles.on)}
          >
            <span className={styles.n} aria-hidden>
              0{step + 1}
            </span>
            <b className="font-display text-[length:clamp(20px,1.8vw,24px)] font-semibold leading-[1.2] tracking-[-0.01em] text-[color:var(--aqt-fg)]">
              {title}
            </b>
            {example ? (
              <code className="font-mono text-caption leading-[1.4] [overflow-wrap:anywhere] text-[color:var(--aqt-fg-dim)]">
                {address(step)}
              </code>
            ) : null}
            <p className="text-ui text-[color:var(--aqt-fg-muted)]">{text}</p>
            {example ? (
              <div className={styles.inlinePreview} aria-hidden>
                {preview(step)}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      {example ? (
        <div className={styles.stage} aria-hidden>
          {steps.map((_, step) => (
            <div key={step} className={cn(styles.frame, step === current && styles.on)}>
              {preview(step)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Swatches({ example, label }: Readonly<{ example: DomainExample; label: string }>) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
      <span className={EYEBROW_CLASS}>{label}</span>
      <span className="flex gap-1.5">
        {example.swatches.map((swatch) => (
          <span
            key={swatch.key}
            title={`${swatch.key}: ${swatch.color}`}
            className="size-[26px] rounded-[7px] border border-[color:var(--aqt-border-2)]"
            style={{ background: swatch.color }}
          />
        ))}
      </span>
    </div>
  );
}

function Dns({
  domain,
  zone,
  cnameOk,
  labels
}: Readonly<{
  domain: string;
  zone: string;
  cnameOk: boolean;
  labels: Record<
    "caption" | "type" | "name" | "value" | "status" | "confirmed" | "working" | "waiting",
    string
  >;
}>) {
  return (
    <div role="table" aria-label={labels.caption}>
      <div
        role="row"
        className={cn(
          DNS_ROW,
          "font-[family-name:var(--aqt-data)] text-label font-semibold uppercase leading-[1.25] tracking-label text-[color:var(--aqt-fg-faint)]"
        )}
      >
        <span role="columnheader">{labels.type}</span>
        <span role="columnheader">{labels.name}</span>
        <span role="columnheader" className="max-sm:hidden">
          {labels.value}
        </span>
        <span role="columnheader" className="max-sm:hidden">
          {labels.status}
        </span>
      </div>
      <div role="row" className={cn(DNS_ROW, "border-t border-[color:var(--aqt-border-3)]")}>
        <span>TXT</span>
        <span className="[overflow-wrap:anywhere]">_owt-verify.{domain}</span>
        <span className="text-[color:var(--aqt-fg-dim)] max-sm:col-start-2">owt-verify-…</span>
        <span
          className={cn(
            OK_PILL,
            "border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_12%,transparent)] text-[color:var(--aqt-emerald)] max-sm:col-start-2"
          )}
        >
          <Check className="size-3.5" aria-hidden />
          {labels.confirmed}
        </span>
      </div>
      <div role="row" className={cn(DNS_ROW, "border-t border-[color:var(--aqt-border)]")}>
        <span>CNAME</span>
        <span className="[overflow-wrap:anywhere]">{domain}</span>
        <span className="text-[color:var(--aqt-fg-dim)] max-sm:col-start-2">{zone}</span>
        {cnameOk ? (
          <span
            className={cn(
              OK_PILL,
              "border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_12%,transparent)] text-[color:var(--aqt-emerald)] max-sm:col-start-2"
            )}
          >
            <Check className="size-3.5" aria-hidden />
            {labels.working}
          </span>
        ) : (
          <span
            className={cn(
              OK_PILL,
              "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-dim)] max-sm:col-start-2"
            )}
          >
            <Clock className="size-3.5" aria-hidden />
            {labels.waiting}
          </span>
        )}
      </div>
    </div>
  );
}
