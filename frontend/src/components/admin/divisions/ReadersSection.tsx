"use client";

import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import type {
  DivisionGridReadinessSource,
  DivisionGridVersion
} from "@/types/workspace.types";

/** A complete mapping is the norm and gets no pill; only the two gaps do. */
const SOURCE_PILL = {
  incomplete: { tone: "warning", key: "impact.mappingIncomplete" },
  missing: { tone: "danger", key: "impact.noMapping" }
} as const;

/**
 * The older versions tournaments still read, from the active version's readiness.
 * Nothing in force, or every tournament already on it: nothing to say.
 */
export function ReadersSection({
  activeVersion,
  loading,
  sources
}: Readonly<{
  activeVersion: DivisionGridVersion | null;
  loading: boolean;
  sources: DivisionGridReadinessSource[];
}>) {
  const t = useTranslations("adminSettings.divisions");
  if (!activeVersion || (!loading && sources.length === 0)) return null;

  return (
    <section className="flex min-w-0 flex-col gap-2" aria-labelledby="divisions-readers">
      <h2 id="divisions-readers" className="text-ui font-semibold text-foreground">
        {t("readersTitle")}
      </h2>
      {loading ? (
        <Skeleton className="h-24 w-full rounded-xl" />
      ) : (
        <ul className="divide-y divide-border">
          {sources.map((source) => (
            <SourceRow key={source.version_id} source={source} target={activeVersion} />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One older version tournaments still read, and whether its divisions have a
 * way into the version in force. The readiness payload names the five newest
 * tournaments and counts all of them, so the names are a sample with the
 * remainder made explicit.
 */
function SourceRow({
  source,
  target
}: Readonly<{ source: DivisionGridReadinessSource; target: DivisionGridVersion }>) {
  const t = useTranslations("adminSettings.divisions");
  const hidden = source.tournament_count - source.tournament_names.length;
  const readers =
    source.tournament_names.length > 0
      ? [...source.tournament_names, hidden > 0 ? t("more", { count: hidden }) : null]
          .filter(Boolean)
          .join(" · ")
      : t("tournamentCount", { count: source.tournament_count });

  return (
    <li className="flex flex-col gap-1 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={source.version_label}>
            {source.version_label}
          </p>
          <p className="truncate text-caption text-muted-foreground" title={source.grid_name}>
            {source.grid_name}
          </p>
        </div>
        {source.status === "ok" ? null : (
          <StatusPill tone={SOURCE_PILL[source.status].tone}>
            {t(SOURCE_PILL[source.status].key)}
          </StatusPill>
        )}
      </div>

      <p className="text-caption text-muted-foreground">{readers}</p>

      {source.status === "ok" ? null : (
        <p className="text-caption text-muted-foreground">
          {source.status === "missing"
            ? t("sourceMissing", { version: target.version })
            : t("sourceIncomplete", {
                count: source.conflict_tiers.length,
                version: target.version
              })}{" "}
          {t("sourceAction")}
        </p>
      )}
    </li>
  );
}
