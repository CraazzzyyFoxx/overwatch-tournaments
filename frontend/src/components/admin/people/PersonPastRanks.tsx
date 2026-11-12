"use client";

import { Fragment, useMemo, type ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { groupPastRanks, signed, type PastGroup } from "@/components/admin/people/personRanks.model";
import { EmptyNote, LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { formatDate } from "@/components/kit/format-time";
import { Skeleton } from "@/components/ui/skeleton";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { registrationRoles } from "@/lib/roster/ontology";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import { HISTORY_RANK_LAYERS, workspacePlayerService } from "@/services/workspace-player.service";
import type { DisciplineMetadata } from "@/types/discipline.types";

/** One page of the newest records: enough for a person's past, and the endpoint's page cap. */
const PAST_LIMIT = 100;

/**
 * «Прошлые оценки»: what the person was rated at when they registered, played a roster or sat in a mix — one entry per
 * tournament or mix, newest first.
 */
export function PersonPastRanks({
  workspaceId,
  personId,
  game,
  axis
}: Readonly<{ workspaceId: number; personId: number; game: string; axis: WorkspaceAxis }>) {
  const t = useTranslations("adminPeople.rank");
  const tOverview = useTranslations("admin.rankOverview");
  const query = useQuery({
    queryKey: adminQueryKeys.rankOverview(workspaceId, { discipline: game, playerId: personId, layers: "history" }),
    queryFn: () =>
      workspacePlayerService.listRanks(workspaceId, {
        discipline: game,
        playerId: personId,
        layer: [...HISTORY_RANK_LAYERS],
        perPage: PAST_LIMIT,
        // Newest first, so a cut-off page drops the oldest records.
        sort: "at",
        order: "desc"
      })
  });
  const metadata = useDisciplineMetadata(axis, game);
  const ontology = metadata.data ?? null;
  const groups = useMemo(
    () => groupPastRanks(query.data?.results ?? [], registrationRoles(ontology).map((role) => role.code)),
    [query.data, ontology]
  );

  return (
    <SettingGroup id="past-ranks" title={t("past")} summary={groups.length || null}>
      {query.isError || metadata.isError ? (
        <LoadErrorNote
          title={tOverview("loadError")}
          onRetry={() => {
            void query.refetch();
            void metadata.refetch();
          }}
        />
      ) : query.isPending || metadata.isPending ? (
        <div className="space-y-2" aria-hidden>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <EmptyNote size="sm">{t("pastEmpty")}</EmptyNote>
      ) : (
        <>
          <ul className="divide-y divide-border/60">
            {groups.map((group) => (
              <PastEntry key={group.key} group={group} ontology={ontology} />
            ))}
          </ul>
          {(query.data?.total ?? 0) > PAST_LIMIT ? (
            <p className="text-caption text-muted-foreground">{t("pastTruncated", { count: PAST_LIMIT })}</p>
          ) : null}
        </>
      )}
    </SettingGroup>
  );
}

function PastEntry({ group, ontology }: Readonly<{ group: PastGroup; ontology: DisciplineMetadata | null }>) {
  const t = useTranslations("adminPeople.rank");
  const format = useFormatter();
  const { context, first, last } = group;
  const kind = context?.kind === "tournament" || context?.kind === "mix" ? context.kind : null;
  const href =
    context?.id == null || kind === null
      ? null
      : kind === "tournament"
        ? `/admin/tournaments/${context.id}`
        : `/balancer/mix/${context.id}`;
  const meta = [
    kind ? t(`pastKinds.${kind}`) : null,
    group.owner,
    first && last ? (
      <span key="when" title={first === last ? formatDate(format, last) : `${formatDate(format, first)} – ${formatDate(format, last)}`}>
        {formatDateRange(format, first, last)}
      </span>
    ) : null
  ].filter(Boolean);

  return (
    <li className="space-y-1 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {href ? (
          <Link href={href} className="text-body font-medium underline-offset-2 hover:text-primary hover:underline">
            {context?.label}
          </Link>
        ) : (
          <span className="text-body font-medium">{context?.label}</span>
        )}
        <span className="text-caption tabular-nums text-muted-foreground">
          {meta.map((part, index) => (
            <Fragment key={index}>
              {index > 0 ? " · " : null}
              {part}
            </Fragment>
          ))}
        </span>
      </div>
      {group.registration.length > 0 ? (
        <PastLine label={t("pastLayers.registration")}>
          {group.registration.map((row, index) => (
            <Fragment key={index}>
              {index > 0 ? " · " : null}
              <RoleValue role={row.role} ontology={ontology} value={row.rank_value} />
            </Fragment>
          ))}
        </PastLine>
      ) : null}
      {group.tournament.length > 0 ? (
        <PastLine label={t("pastLayers.tournament")}>
          {group.tournament.map((row, index) => (
            <Fragment key={index}>
              {index > 0 ? " · " : null}
              <RoleValue role={row.role} ontology={ontology} value={row.rank_value} />
            </Fragment>
          ))}
        </PastLine>
      ) : null}
      {group.casual.length > 0 ? (
        <PastLine label={t("pastLayers.casual")}>
          {group.casual.map((run, index) => (
            <Fragment key={index}>
              {index > 0 ? " · " : null}
              <span className="inline-flex flex-wrap items-center gap-x-1">
                {run[0].role ? <PlayerRoleIcon role={run[0].role} ontology={ontology} size={14} /> : null}
                {run.map((row, step) => (
                  <Fragment key={step}>
                    {step > 0 ? " → " : null}
                    <span className="tabular-nums text-foreground">{row.rank_value}</span>
                    {row.delta == null ? null : <span className="tabular-nums">{signed(row.delta)}</span>}
                  </Fragment>
                ))}
              </span>
            </Fragment>
          ))}
        </PastLine>
      ) : null}
    </li>
  );
}

function PastLine({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-caption text-muted-foreground">
      <span>{label}:</span>
      {children}
    </p>
  );
}

/** A role glyph (none for a role-less record) and the number. */
function RoleValue({
  role,
  ontology,
  value
}: Readonly<{ role: string | null; ontology: DisciplineMetadata | null; value: number }>) {
  return (
    <span className="inline-flex items-center gap-1">
      {role ? <PlayerRoleIcon role={role} ontology={ontology} size={14} /> : null}
      <span className="tabular-nums text-foreground">{value}</span>
    </span>
  );
}
