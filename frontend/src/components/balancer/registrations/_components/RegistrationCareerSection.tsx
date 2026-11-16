"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { useRoleCodeName } from "@/hooks/useRoleName";
import { useFormatter } from "@/lib/datetime/client";
import { getPlayerSlug } from "@/lib/player";
import { ratedDimension, roleTint, type LadderedOntology } from "@/lib/roster/ontology";
import type { CareerUserSignals } from "@/types/career-signals.types";

import { signalTone, sortSignals } from "./careerSignals";
import { useSignalLabel } from "./careerSignalsColumn";

const DAY_MS = 86_400_000;

/**
 * What the collected game career says about the registrant: the signals with full wording (naming the account they
 * are about), the split of this season's competitive time over the game's roles, total hours and last game. The
 * public profile's ladder tab holds the rest.
 */
export default function RegistrationCareerSection({
  ontology,
  signals
}: Readonly<{
  ontology: LadderedOntology | null;
  signals: CareerUserSignals;
}>) {
  const t = useTranslations("registrationsAdmin.career");
  const format = useFormatter();
  const label = useSignalLabel();
  const roleName = useRoleCodeName(ontology);
  const [now] = useState(() => Date.now());
  const lastPlayed = signals.last_played_at ? new Date(signals.last_played_at) : null;
  const days = lastPlayed ? Math.max(0, Math.floor((now - lastPlayed.getTime()) / DAY_MS)) : null;
  const wording = (signal: CareerUserSignals["signals"][number]) => {
    const text = label("full", signal, {
      hours: signal.value == null ? "" : format.number(signal.value, { maximumFractionDigits: 0 }),
      days: days ?? ""
    });
    return signal.handle ? `${text} · ${signal.handle}` : text;
  };

  const dimension = ontology ? ratedDimension(ontology)?.code : undefined;
  const order = (code: string) => ontology?.roles.find((role) => role.dimension === dimension && role.code === code)?.sort_order ?? Infinity;
  const shares = Object.entries(signals.competitive_role_shares)
    .filter(([, share]) => share > 0)
    .sort(([a], [b]) => order(a) - order(b));
  const slug = getPlayerSlug(signals.user_name);

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <h3 className={eyebrowClass("muted")}>{t("title")}</h3>
        {slug ? (
          <Button asChild variant="link" size="sm" className="h-auto shrink-0 gap-1 p-0 text-xs">
            <Link href={`/users/${slug}?tab=ladder`}>
              {t("openProfile")}
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        ) : null}
      </div>

      {signals.signals.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("noSignals")}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {sortSignals(signals.signals).map((signal, index) => (
            <li key={`${signal.code}-${signal.social_account_id ?? index}`}>
              <Badge tone={signalTone(signal.code)} size="sm">
                {wording(signal)}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {shares.length > 0 ? (
        <div className="space-y-1.5">
          <div role="img" aria-label={t("roleShares")} className="flex h-2 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
            {shares.map(([code, share]) => (
              <span key={code} style={{ width: `${share * 100}%`, backgroundColor: ontology ? roleTint(ontology, code) : undefined }} />
            ))}
          </div>
          <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-label text-[color:var(--aqt-fg-muted)]">
            {shares.map(([code, share]) => (
              <li key={code} className="inline-flex items-center gap-1.5">
                <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: ontology ? roleTint(ontology, code) : undefined }} />
                {roleName(code)}
                <span className="tabular-nums">{format.number(share, { style: "percent", maximumFractionDigits: 0 })}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="text-label text-[color:var(--aqt-fg-dim)]">
        {[
          t("hours", { hours: format.number(signals.hours, { maximumFractionDigits: 0 }) }),
          lastPlayed ? t("lastGame", { when: format.relativeTime(lastPlayed, now) }) : t("noGames")
        ].join(" · ")}
      </p>
    </section>
  );
}
