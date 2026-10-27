"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { MasterDetail } from "@/components/kit/MasterDetail";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import pickBanService from "@/services/pickBan.service";
import type { PickBanConfig, PickBanKind } from "@/types/tournament.types";
import {
  pickBanDraftToInput,
  type PickBanDraft
} from "@/lib/tournament/pick-ban-config";
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
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useKindLabel } from "@/hooks/useKindLabel";

export default function PreGameSettingsPage() {
  return (
    <SettingsSectionPage
      section="pre-game"
      description={useTranslations("adminTournament.screenDescriptions")("preGame")}
    >
      {({ tournamentId, workspaceId, tournament }) => (
        <PreGamePhase
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          discipline={tournament.discipline}
        />
      )}
    </SettingsSectionPage>
  );
}

function PreGamePhase({
  tournamentId,
  workspaceId,
  discipline
}: Readonly<{ tournamentId: number; workspaceId: number; discipline: string }>) {
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

  // One catalogue query per kind of the tournament's own game, both gated on the kind on screen.
  const mapsQuery = useCatalogEntities(discipline, "map", { enabled: kind === "map" });
  const heroesQuery = useCatalogEntities(discipline, "character", { enabled: kind === "hero" });
  // A game whose maps belong to no mode (Deadlock's Midtown hosts all of them) names a match's mode apart from its
  // map, so its pool may hold modes too. A game that files each map under a mode (Overwatch) says it through the map.
  const descriptor = useGameDescriptors().get(discipline);
  const kindLabel = useKindLabel();
  const offersModes =
    kind === "map" &&
    descriptor != null &&
    "mode" in descriptor.kinds &&
    mapsQuery.data != null &&
    mapsQuery.data.every((map) => map.parent_id == null);
  const modesQuery = useCatalogEntities(discipline, "mode", { enabled: offersModes });

  const catalogue = useMemo<CatalogueItem[]>(() => {
    if (kind === "map") {
      // Maps and modes share the pool, so each is filed under its kind for the picker's group filter.
      const mapGroup = offersModes && descriptor ? kindLabel(descriptor, "map") : null;
      // Off-rotation maps (a retired brawl-only map) are not something an
      // organizer bans or picks in a ranked series.
      const maps = (mapsQuery.data ?? [])
        .filter((map) => map.attrs.in_competitive !== false)
        .map((map) => ({
          id: map.id,
          name: map.name,
          group: map.parent?.name ?? mapGroup,
          imageSrc: map.image_path ?? null
        }));
      if (!offersModes || !descriptor) return maps;
      const modeGroup = kindLabel(descriptor, "mode");
      return [
        ...maps,
        ...(modesQuery.data ?? []).map((mode) => ({
          id: mode.id,
          name: mode.name,
          group: modeGroup,
          imageSrc: mode.image_path ?? null,
          isMode: true
        }))
      ];
    }
    return (heroesQuery.data ?? []).map((hero) => ({
      id: hero.id,
      name: hero.name,
      group: typeof hero.attrs.class === "string" ? hero.attrs.class : null,
      imageSrc: hero.image_path ?? null
    }));
  }, [kind, mapsQuery.data, heroesQuery.data, modesQuery.data, offersModes, descriptor, kindLabel]);

  const catalogueLoading =
    kind === "map" ? mapsQuery.isPending || (offersModes && modesQuery.isPending) : heroesQuery.isPending;

  const stages = useMemo(() => stagesQuery.data ?? [], [stagesQuery.data]);
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
    mutationFn: async (drafts: PickBanDraft[]) => {
      for (const one of drafts) {
        await pickBanService.upsertConfig(tournamentId, pickBanDraftToInput(one));
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

  const failedQuery = configsQuery.isError ? configsQuery : stagesQuery.isError ? stagesQuery : null;
  if (failedQuery) {
    return (
      <PageStateCard
        state="error"
        title={t("loadFailed")}
        onAction={() => void failedQuery.refetch()}
      />
    );
  }

  if (stagesQuery.isLoading || configsQuery.isPending) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Map veto and hero bans are two independent configs per scope, so the
          kind is part of what is being edited, not a filter over one list,
          and the tree's inherited/overridden markers only mean anything for
          one of them at a time. */}
      <ToggleGroup
        variant="pill"
        size="sm"
        className="self-start"
        value={kind}
        onValueChange={(next) => {
          if (next) setParams({ kind: next });
        }}
        aria-label={t("kindLabel")}
      >
        {PRE_GAME_KINDS.map((value) => (
          <ToggleGroupItem key={value} value={value}>
            {t(value === "map" ? "kindMap" : "kindHero")}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

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
              tournamentId={tournamentId}
              discipline={discipline}
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
              onSave={(drafts) => upsertMutation.mutate(drafts)}
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
