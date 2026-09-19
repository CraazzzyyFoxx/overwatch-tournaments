"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { MasterDetail } from "@/components/kit/MasterDetail";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import heroService from "@/services/hero.service";
import mapService from "@/services/map.service";
import pickBanService from "@/services/pickBan.service";
import type { PickBanConfig, PickBanKind } from "@/types/tournament.types";
import {
  pickBanDraftToInput,
  type PickBanDraft
} from "@/lib/pick-ban-config";
import { useHubEncountersQuery, useHubStagesQuery } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { PreGameEditor } from "./PreGameEditor";
import { ScopeTree } from "./ScopeTree";
import type { CatalogueItem } from "./CataloguePicker";
import {
  PRE_GAME_KINDS,
  PRE_GAME_STEPS,
  decodePreGameScope,
  encodePreGameScope,
  type PreGameScope,
  type PreGameStep
} from "./pre-game-scope";

export default function PreGameSettingsPage() {
  return (
    <SettingsSectionPage
      section="pre-game"
      description="Map veto and hero pick/ban per scope. Child scopes inherit until overridden."
    >
      {({ tournamentId, workspaceId }) => (
        <PreGamePhase tournamentId={tournamentId} workspaceId={workspaceId} />
      )}
    </SettingsSectionPage>
  );
}

function PreGamePhase({
  tournamentId,
  workspaceId
}: Readonly<{ tournamentId: number; workspaceId: number }>) {
  const t = useTranslations("pickBan.admin");
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const canManage = canAccessPermission("match.update", workspaceId);

  // Scope is a `Link` (a push, so Back leaves a scope and `MasterDetail`'s
  // narrow-viewport Back button returns to the tree). Step and kind are
  // written here instead, and replace rather than push: flipping between the
  // three steps of one form must not fill the history with the same page.
  const { searchParams, setParams } = useQueryParams({ mode: "replace", resetOnChange: [] });
  const scope = decodePreGameScope(searchParams?.get("scope"));
  const stepParam = searchParams?.get("step");
  const step: PreGameStep = (PRE_GAME_STEPS as readonly string[]).includes(stepParam ?? "")
    ? (stepParam as PreGameStep)
    : "pool";
  const kindParam = searchParams?.get("kind");
  const kind: PickBanKind = kindParam === "hero" ? "hero" : "map";

  const stagesQuery = useHubStagesQuery(tournamentId);
  // Shares its key and its cache with the other hub tabs, so this is usually
  // already resolved. Deliberately not gated on: the scope tree degrades to
  // each stage's predicted rounds while it is in flight.
  const encountersQuery = useHubEncountersQuery(tournamentId);

  const configsQueryKey = ["admin", "tournament", tournamentId, "pick-ban-configs"] as const;
  const configsQuery = useQuery({
    queryKey: configsQueryKey,
    queryFn: () => pickBanService.listConfigs(tournamentId)
  });
  const configs = useMemo(() => configsQuery.data?.configs ?? [], [configsQuery.data]);

  // One catalogue query per kind, both gated on the kind on screen.
  const mapsQuery = useQuery({
    queryKey: ["maps", "all", "gamemode"],
    queryFn: () =>
      mapService.getAll({ perPage: -1, sort: "name", order: "asc", entities: ["gamemode"] }),
    enabled: kind === "map"
  });
  const heroesQuery = useQuery({
    queryKey: ["heroes", "all"],
    queryFn: () => heroService.getAll({ perPage: -1, sort: "name", order: "asc" }),
    enabled: kind === "hero"
  });

  const catalogue = useMemo<CatalogueItem[]>(() => {
    if (kind === "map") {
      // Off-rotation maps (a retired brawl-only map) are not something an
      // organizer bans or picks in a ranked series.
      return (mapsQuery.data?.results ?? [])
        .filter((map) => map.in_competitive !== false)
        .map((map) => ({
          id: map.id,
          name: map.name,
          group: map.gamemode?.name ?? null,
          imageSrc: map.image_path ?? null
        }));
    }
    return (heroesQuery.data?.results ?? []).map((hero) => ({
      id: hero.id,
      name: hero.name,
      group: hero.type ?? hero.role ?? null,
      imageSrc: hero.image_path ?? null
    }));
  }, [kind, mapsQuery.data, heroesQuery.data]);

  const catalogueLoading = kind === "map" ? mapsQuery.isPending : heroesQuery.isPending;

  const stages = stagesQuery.data ?? [];
  const stagesById = useMemo(() => new Map(stages.map((stage) => [stage.id, stage])), [stages]);
  const describeScope = (target: Pick<PickBanConfig, "stage_id" | "round">): string => {
    if (target.stage_id == null) return t("tournamentLevel");
    const name = stagesById.get(target.stage_id)?.name ?? t("unknownStage", { id: target.stage_id });
    return target.round == null
      ? t("scopeStage", { stage: name })
      : t("scopeStageRound", { stage: name, round: target.round });
  };

  const upsertMutation = useMutation({
    // One write per job, sequentially: a stage-wide slot pool is one config per
    // round of that stage, and a half-written stage is easier to reason about
    // in order than out of it.
    mutationFn: async (jobs: Array<{ draft: PickBanDraft; seriesLength: number }>) => {
      for (const job of jobs) {
        await pickBanService.upsertConfig(
          tournamentId,
          pickBanDraftToInput(job.draft, job.seriesLength)
        );
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: configsQueryKey });
      notify.success(t("saved"));
    },
    onError: (error) => notify.apiError(error, { title: t("saveFailed") })
  });

  const deleteMutation = useMutation({
    mutationFn: (configId: number) => pickBanService.deleteConfig(configId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: configsQueryKey });
      notify.success(t("deleted"));
    },
    onError: (error) => notify.apiError(error, { title: t("deleteFailed") })
  });

  const basePath = `/admin/tournaments/${tournamentId}/settings/pre-game`;
  const hrefFor = (target: PreGameScope) =>
    `${basePath}?scope=${encodePreGameScope(target)}&kind=${kind}&step=${step}`;


  if (configsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTriangle aria-hidden className="size-4" />
        <AlertDescription className="flex flex-wrap items-center gap-3">
          <span>{t("loadFailed")}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => configsQuery.refetch()}>
            {t("retry")}
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (stagesQuery.isLoading || configsQuery.isPending) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Map veto and hero bans are two independent configs per scope, so the
          kind is part of what is being edited, not a filter over one list —
          and the tree's inherited/overridden markers only mean anything for
          one of them at a time. A `Select`, not a tab row: the step tabs below
          are this screen's tabs. */}
      <div className="flex items-center gap-2">
        <Label htmlFor="pre-game-kind" className="text-xs text-muted-foreground">
          {t("kindLabel")}
        </Label>
        <Select value={kind} onValueChange={(next) => setParams({ kind: next })}>
          <SelectTrigger id="pre-game-kind" className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRE_GAME_KINDS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(value === "map" ? "kindMap" : "kindHero")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <MasterDetail
        listWidth={260}
        list={
          <ScopeTree
            kind={kind}
            stages={stages}
            encounters={encountersQuery.data?.results}
            configs={configs}
            selected={scope}
            hrefFor={hrefFor}
          />
        }
        detail={
          scope == null ? null : (
            <PreGameEditor
              scope={scope}
              kind={kind}
              step={step}
              onStepChange={(next) => setParams({ step: next })}
              stages={stages}
              encounters={encountersQuery.data?.results}
              configs={configs}
              catalogue={catalogue}
              catalogueLoading={catalogueLoading}
              canManage={canManage}
              describeScope={describeScope}
              saving={upsertMutation.isPending}
              resetting={deleteMutation.isPending}
              onSave={(jobs) => upsertMutation.mutate(jobs)}
              onResetToInherited={(configId) => deleteMutation.mutate(configId)}
            />
          )
        }
        emptyDetail={
          <PageStateCard
            state="empty"
            title={t("pickScopeTitle")}
            description={t("pickScopeHint")}
          />
        }
      />
    </div>
  );
}
