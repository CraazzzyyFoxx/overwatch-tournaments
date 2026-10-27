import { ChartColumn, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { owtButton } from "@/components/site/owt-button";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Separator } from "@/components/ui/separator";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { BRAND_NAME } from "@/config/site";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import { suggestSlug } from "@/lib/workspace/slug";

import styles from "./community-preview.module.css";

export type SlugKind = "neutral" | "ok" | "err";

const SLUG_CLASS: Record<SlugKind, string> = {
  neutral: "text-[color:var(--aqt-fg)]",
  ok: "text-[color:var(--aqt-fg)]",
  err: "text-[color:var(--aqt-rose-text)]"
};

/** The Directory card's logo glow. */
const LOGO_CLASS =
  "shadow-[0_0_0_1px_var(--aqt-overlay-border),0_12px_36px_-12px_color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]";

/**
 * The community page the create form is about to make, built from what is
 * typed: the address in the window's bar, then the page's header and hero as
 * a new community's page shows them (initials logo, "since" this year, the two
 * buttons, nothing played yet). Until something is typed it shows the
 * placeholder's example, dimmed.
 *
 * Only the address is read out: it is the slug field's description
 * (`addressId`), the platform address with the slug as typed. The rest repeats
 * the form and is hidden from assistive tech.
 */
export function CommunityPreview({
  name,
  slug,
  slugKind,
  year,
  addressId
}: Readonly<{ name: string; slug: string; slugKind: SlugKind; year: number; addressId: string }>) {
  const t = useTranslations("getWorkspace.create");
  const page = useTranslations("workspace");
  const nav = useTranslations("nav");
  const example = t("exampleName");
  const shown = name || example;
  const avatar = { id: 0, name: shown, icon_url: null };

  return (
    <div className={styles.stage}>
      <div className={styles.screen}>
        <div className="flex items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3 py-2">
          {/* Off on a phone, where the full address needs the bar's width. */}
          <span aria-hidden className="hidden shrink-0 gap-1.5 sm:flex">
            {[0, 1, 2].map((dot) => (
              <span key={dot} className="size-2 rounded-full bg-[color:var(--aqt-border-3)]" />
            ))}
          </span>
          <p
            id={addressId}
            className="flex min-w-0 flex-1 items-start gap-1.5 rounded-md bg-[color:var(--aqt-overlay-3)] px-2.5 py-1 font-mono text-caption leading-snug text-[color:var(--aqt-fg-dim)]"
          >
            <Lock aria-hidden className="mt-[3px] size-3 shrink-0" />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {PLATFORM_ZONE}/workspace/
              <wbr />
              {slug ? (
                <b className={cn("font-semibold", SLUG_CLASS[slugKind])}>{slug}</b>
              ) : (
                <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">
                  {suggestSlug(example)}
                </span>
              )}
            </span>
          </p>
        </div>

        <div aria-hidden>
          <div className="flex h-11 items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3.5">
            <Image src="/brand-mark.svg" alt="" width={18} height={18} className="rounded-[4px]" />
            <b className="font-display text-body font-extrabold leading-none tracking-[0.02em]">{BRAND_NAME}</b>
            <Separator orientation="vertical" className="h-4 bg-[color:var(--aqt-border-2)]" />
            <WorkspaceAvatar workspace={avatar} size={20} />
            <span className="min-w-0 truncate text-caption text-[color:var(--aqt-fg-muted)]">{shown}</span>
            <span className="ml-auto hidden shrink-0 gap-3.5 text-label text-[color:var(--aqt-fg-dim)] sm:flex">
              <span>{nav("groups.tournaments")}</span>
              <span>{nav("groups.users")}</span>
              <span>{nav("items.mixes.title")}</span>
            </span>
          </div>

          <div className={cn(styles.page, "px-5 pb-4 pt-5")}>
            <Eyebrow>{page("since", { year })}</Eyebrow>
            <div className="mt-2.5 flex min-w-0 items-center gap-3.5">
              <WorkspaceAvatar workspace={avatar} size={52} className={LOGO_CLASS} />
              <b
                className={cn(
                  "min-w-0 truncate font-display text-title font-bold lg:text-headline",
                  name ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-faint)]"
                )}
              >
                {shown}
              </b>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className={owtButton({ variant: "primary", size: "sm" })}>{page("allTournaments")}</span>
              <span className={owtButton({ variant: "outline", size: "sm" })}>
                <ChartColumn aria-hidden />
                {page("statistics")}
              </span>
            </div>
            <p className="mt-4 border-t border-[color:var(--aqt-border)] pt-3 text-caption text-[color:var(--aqt-fg-dim)]">
              {t("previewCounts")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
