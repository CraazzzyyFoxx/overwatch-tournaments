"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Star, Trash2 } from "lucide-react";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { SaveBar } from "@/components/kit/SaveBar";
import { Button } from "@/components/ui/button";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import type {
  DivisionGridActivationReadiness,
  DivisionGridVersion
} from "@/types/workspace.types";

import { VERSION_STATE_TONE, versionState } from "../versionStatus";
import { autoMap, mappingRules, unresolvedRows } from "./autoMap";
import { ChangesView } from "./ChangesView";
import { DivisionsTable } from "./DivisionsTable";
import { ImpactColumn } from "./ImpactColumn";
import { LadderColumn } from "./LadderColumn";
import { MappingsView, type MappingSource } from "./MappingsView";
import { publishChecks, readyToPublish } from "./publishChecks";
import {
  bandsDifferingFromBase,
  bandsFromTiers,
  describeEdits,
  diffBands,
  draftReducer,
  initDraftState,
  RANK_COUNT,
  tiersFromBands,
  type Band
} from "./draftReducer";

/** The right rail becomes a sub-tab below this width (F12 ·8). */
const RAIL_MEDIA_QUERY = "(min-width: 1280px)";

const TAB_KEYS = ["divisions", "changes", "mappings", "impact"] as const;
type TabKey = (typeof TAB_KEYS)[number];

export interface DraftEditorProps {
  workspaceId: number;
  version: DivisionGridVersion;
  /** The parent version's bands; empty when this version has no parent. */
  base: Band[];
  baseLabel: string;
  readiness: DivisionGridActivationReadiness | null;
  activeVersionId: number | null;
  editable: boolean;
  canPublish: boolean;
  canDelete: boolean;
  /**
   * Re-mounts this editor from the cache. Both "saved" and "discard my edits"
   * are the same thing to a reducer holding a snapshot stack: throw it away and
   * read the version again.
   */
  onReload: () => void;
}

/**
 * The draft division-grid editor (F12): ladder on the left, three views in the
 * middle, impact on the right, one save bar underneath.
 *
 * Everything structural goes through `draftReducer`, so this component owns no
 * band arithmetic — only which view is open, what has been chosen in Mappings,
 * and the four requests (save, publish, activate, delete).
 *
 * A published or active version opens here read-only: a version another
 * tournament may already have been played on is immutable by design, and the
 * way forward is a new draft cloned from it.
 */
export function DraftEditor({
  workspaceId,
  version,
  base,
  baseLabel,
  readiness,
  activeVersionId,
  editable,
  canPublish,
  canDelete,
  onReload
}: Readonly<DraftEditorProps>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { searchParams, setParams } = useQueryParams();
  const [state, dispatch] = useReducer(
    draftReducer,
    { tiers: version.tiers, base },
    (seed) => initDraftState(bandsFromTiers(seed.tiers), seed.base)
  );
  const [manualChoice, setManualChoice] = useState<Record<number, number | undefined>>({});
  const [confirming, setConfirming] = useState<"publish" | "delete" | null>(null);
  const [iconTarget, setIconTarget] = useState<number | null>(null);
  const iconInputRef = useRef<HTMLInputElement>(null);

  const [isWide, setIsWide] = useState(true);
  useEffect(() => {
    const query = window.matchMedia(RAIL_MEDIA_QUERY);
    const sync = () => setIsWide(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  const sources = readiness?.sources ?? [];
  const dirty = state.history.length > 0;
  // Mapping rules key on target tier ids, so an unsaved band cannot be a target.
  const mappable = state.bands.every((band) => band.id !== undefined);

  const sourceQueries = useQueries({
    queries: sources.map((source) => ({
      queryKey: ["division-grid-version", source.version_id],
      queryFn: () => workspaceService.getDivisionGridVersion(source.version_id)
    }))
  });
  const mappingQueries = useQueries({
    queries: sources.map((source) => ({
      queryKey: ["division-grid-mapping", source.version_id, version.id],
      queryFn: () => workspaceService.getDivisionGridMapping(source.version_id, version.id),
      // A version pair with no mapping yet is the normal starting state, not a
      // failure to retry.
      retry: false
    }))
  });

  const mappingSources = useMemo<MappingSource[]>(
    () =>
      sources.flatMap((source, index) => {
        const tiers = sourceQueries[index]?.data?.tiers;
        return tiers ? [{ readiness: source, tiers }] : [];
      }),
    [sources, sourceQueries]
  );

  /**
   * Primary targets already stored server-side, overlaid with this session's
   * choices — derived rather than copied into state on load, so a refetch can
   * never silently drop a decision the user just made.
   */
  const chosen = useMemo(() => {
    const stored: Record<number, number | undefined> = {};
    for (const query of mappingQueries) {
      for (const rule of query.data?.rules ?? []) {
        if (rule.is_primary) stored[rule.source_tier_id] = rule.target_tier_id;
      }
    }
    return { ...stored, ...manualChoice };
  }, [mappingQueries, manualChoice]);

  const unresolvedMappings = useMemo(
    () =>
      mappingSources.reduce(
        (total, source) =>
          total + unresolvedRows(autoMap(source.tiers, state.bands), chosen).length,
        0
      ),
    [chosen, mappingSources, state.bands]
  );

  const checks = publishChecks({
    bands: state.bands,
    readiness,
    unresolvedMappings,
    mappable,
    dirty
  });
  const publishable = readyToPublish(checks);
  const edits = useMemo(() => describeEdits(state), [state]);
  const changeCount = useMemo(() => {
    const diff = diffBands(state.base, state.bands);
    return diff.added.length + diff.removed.length + diff.moved.length + diff.renamed.length;
  }, [state.base, state.bands]);

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["division-grid-readiness"] }),
      queryClient.invalidateQueries({ queryKey: ["division-grid-versions"] }),
      queryClient.invalidateQueries({ queryKey: ["division-grids"] }),
      queryClient.invalidateQueries({ queryKey: ["division-grid-mapping"] })
    ]);
  }, [queryClient]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const updated = await workspaceService.updateDivisionGridVersion(version.id, {
        tiers: tiersFromBands(state.bands)
      });
      // Mappings are written against the SAVED tiers: the rules point at tier
      // ids, and a band created in this session only gets one here.
      const savedBands = bandsFromTiers(updated.tiers);
      for (const source of mappingSources) {
        const rules = mappingRules(autoMap(source.tiers, savedBands), chosen);
        if (rules.length === 0) continue;
        await workspaceService.putDivisionGridMapping(source.readiness.version_id, version.id, {
          name: `${source.readiness.version_label} \u2192 ${updated.label}`,
          rules
        });
      }
      return updated;
    },
    onSuccess: async (updated) => {
      // Seed the cache before remounting, so the fresh editor reads the tiers
      // that were just saved rather than the ones it sent.
      queryClient.setQueryData(["division-grid-version", version.id], updated);
      setManualChoice({});
      await invalidate();
      notify.success(`v${updated.version} draft saved`);
      onReload();
    },
    onError: reportFailure("Draft could not be saved")
  });

  const publishMutation = useMutation({
    mutationFn: () => workspaceService.publishDivisionGridVersion(version.id),
    onSuccess: async (published) => {
      queryClient.setQueryData(["division-grid-version", version.id], published);
      await invalidate();
      notify.success(`v${published.version} published`);
      onReload();
    },
    onError: reportFailure("Version could not be published")
  });

  const activateMutation = useMutation({
    mutationFn: () => workspaceService.activateDivisionGridVersion(workspaceId, version.id),
    onSuccess: async () => {
      await invalidate();
      notify.success(`v${version.version} is now the workspace grid`);
      onReload();
    },
    onError: reportFailure("Version could not be activated")
  });

  const deleteMutation = useMutation({
    mutationFn: () => workspaceService.deleteDivisionGridVersion(version.id),
    onSuccess: async () => {
      await invalidate();
      notify.success("Draft discarded");
      router.push("/admin/settings/divisions");
    },
    onError: reportFailure("Draft could not be discarded")
  });

  const iconMutation = useMutation({
    mutationFn: async ({ bandIndex, file }: { bandIndex: number; file: File }) => {
      const band = state.bands[bandIndex];
      const suffix = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
      const upload = await workspaceService.uploadDivisionIcon(
        `${band.slug}-${suffix}`,
        file,
        workspaceId
      );
      return { bandIndex, url: upload.public_url };
    },
    onSuccess: ({ bandIndex, url }) => dispatch({ type: "setIcon", bandIndex, iconUrl: url }),
    onError: reportFailure("Crest could not be uploaded")
  });

  const onPickIcon = useCallback((bandIndex: number) => {
    setIconTarget(bandIndex);
    iconInputRef.current?.click();
  }, []);

  const selectedSlug = searchParams?.get("band") ?? null;
  const requestedTab = (searchParams?.get("tab") ?? "divisions") as TabKey;
  const tab: TabKey = TAB_KEYS.includes(requestedTab) ? requestedTab : "divisions";
  // On `xl` the impact rail is always on screen, so its tab has nowhere to go.
  const activeTab: TabKey = isWide && tab === "impact" ? "divisions" : tab;

  /**
   * Absolute, and carrying the rest of the query: `?band=` has to survive a
   * view switch, and a query-only href would resolve against whatever path the
   * router last rendered.
   */
  const tabHref = (next: TabKey) => {
    const query = new URLSearchParams(searchParams?.toString() ?? "");
    query.set("tab", next);
    return `/admin/settings/divisions/v/${version.id}?${query.toString()}`;
  };

  const tabs: LinkTabItem[] = [
    { key: "divisions", label: "Divisions", href: tabHref("divisions") },
    {
      key: "changes",
      label: "Changes",
      href: tabHref("changes"),
      badge: changeCount || undefined
    },
    {
      key: "mappings",
      label: "Mappings",
      href: tabHref("mappings"),
      badge: unresolvedMappings || undefined
    },
    {
      key: "impact",
      label: "Impact",
      href: tabHref("impact"),
      hidden: isWide
    }
  ];

  const lifecycle = versionState(version, activeVersionId);
  const intent: ConfirmIntent =
    confirming === "delete"
      ? {
          title: `Discard draft v${version.version}?`,
          description:
            "The draft version and every edit in it are deleted. The workspace keeps the version it uses now.",
          confirmLabel: "Discard draft",
          tone: "danger"
        }
      : {
          title: `Publish v${version.version}?`,
          description:
            "A published version becomes immutable: tournaments can be pinned to it, and changing the divisions afterwards means a new draft. Publishing does not make it the workspace grid — activate it separately.",
          confirmLabel: `Publish v${version.version}`,
          tone: "warning"
        };

  return (
    <div className="flex flex-col gap-4">
      <EntityHubHeader
        backHref="/admin/settings/divisions"
        title={version.label}
        status={{
          label: `v${version.version} · ${lifecycle}`,
          tone: VERSION_STATE_TONE[lifecycle]
        }}
        meta={[
          base.length > 0 ? `Created from ${baseLabel}` : "No parent version",
          `${state.bands.length} divisions`,
          `${RANK_COUNT} ranks`
        ]}
        actions={
          <>
            {editable ? (
              <Button
                variant="outline"
                size="sm"
                disabled={!dirty}
                onClick={() => dispatch({ type: "undo" })}
              >
                <RotateCcw aria-hidden className="size-4" />
                Undo last change
              </Button>
            ) : null}
            {editable && canDelete ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirming("delete")}>
                <Trash2 aria-hidden className="size-4" />
                Discard draft
              </Button>
            ) : null}
            {canPublish && version.status === "draft" ? (
              <Button
                size="sm"
                disabled={!publishable || publishMutation.isPending}
                title={
                  publishable
                    ? undefined
                    : "Resolve everything under “Ready to publish?” first — unsaved edits and open mapping decisions block a publish."
                }
                onClick={() => setConfirming("publish")}
              >
                Publish v{version.version}
              </Button>
            ) : null}
            {canPublish && version.status !== "draft" && version.id !== activeVersionId ? (
              <Button
                size="sm"
                disabled={readiness?.is_ready !== true || activateMutation.isPending}
                title={
                  readiness?.is_ready === true
                    ? undefined
                    : "Every older version a tournament still reads needs a complete mapping first."
                }
                onClick={() => activateMutation.mutate()}
              >
                <Star aria-hidden className="size-4" />
                Activate v{version.version}
              </Button>
            ) : null}
          </>
        }
      />

      {!editable ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-3">
          <p className="text-sm text-muted-foreground">
            {version.status === "draft"
              ? "You can read this draft but not change it — editing needs the division_grid.update permission."
              : "Published versions are immutable, because tournaments are pinned to them. Clone this version to change anything."}
          </p>
          {version.status !== "draft" && canPublish ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void workspaceService
                  .cloneDivisionGridVersion(version.id)
                  .then(async (draft) => {
                    await invalidate();
                    router.push(`/admin/settings/divisions/v/${draft.id}`);
                  })
                  .catch(reportFailure("Draft could not be created"));
              }}
            >
              Create draft from this version
            </Button>
          ) : null}
        </div>
      ) : null}

      <input
        ref={iconInputRef}
        type="file"
        accept="image/png,image/webp,image/svg+xml"
        className="hidden"
        aria-hidden
        tabIndex={-1}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && iconTarget !== null) iconMutation.mutate({ bandIndex: iconTarget, file });
          event.target.value = "";
        }}
      />

      <div
        className={cn(
          "grid items-start gap-4",
          "xl:grid-cols-[230px_minmax(0,1fr)_250px]"
        )}
      >
        <LadderColumn
          bands={state.bands}
          selectedSlug={selectedSlug}
          editable={editable}
          onSelect={(slug) => setParams({ band: slug })}
          dispatch={dispatch}
        />

        <div className="flex min-w-0 flex-col gap-3">
          <LinkTabs
            items={tabs}
            activeKey={activeTab}
            level={2}
            ariaLabel="Draft editor views"
          />

          {activeTab === "divisions" ? (
            <DivisionsTable
              bands={state.bands}
              base={state.base}
              editable={editable}
              selectedSlug={selectedSlug}
              onSelect={(slug) => setParams({ band: slug })}
              dispatch={dispatch}
              onPickIcon={onPickIcon}
            />
          ) : null}

          {activeTab === "changes" ? (
            <ChangesView base={state.base} bands={state.bands} baseLabel={baseLabel} />
          ) : null}

          {activeTab === "mappings" ? (
            <MappingsView
              targetLabel={`v${version.version}`}
              bands={state.bands}
              sources={mappingSources}
              chosen={chosen}
              onChoose={(sourceTierId, targetTierId) =>
                setManualChoice((current) => ({ ...current, [sourceTierId]: targetTierId }))
              }
              editable={editable}
              mappable={mappable}
              loading={sourceQueries.some((query) => query.isLoading)}
            />
          ) : null}

          {activeTab === "impact" ? (
            <ImpactColumn checks={checks} sources={sources} edits={edits} />
          ) : null}
        </div>

        {isWide ? <ImpactColumn checks={checks} sources={sources} edits={edits} /> : null}
      </div>

      {editable ? (
        <SaveBar
          dirty={dirty}
          saving={saveMutation.isPending}
          primaryLabel="Save draft"
          summary={
            <>
              <strong>
                v{version.version} {version.status}
              </strong>{" "}
              · {state.bands.length} divisions · {state.history.length}{" "}
              {state.history.length === 1 ? "edit" : "edits"} ·{" "}
              {bandsDifferingFromBase(state.base, state.bands)} bands differ from {baseLabel}
            </>
          }
          onDiscard={onReload}
          onSave={() => saveMutation.mutate()}
          // Divisions · Changes · Mappings · Impact are `?tab=` links of THIS
          // editor, and "resolve the open mapping decisions" is exactly what
          // the publish pre-flight sends a dirty draft off to do. Prompting
          // for a discard on the way there would make that unreachable.
          guardNavigation={false}
        />
      ) : null}

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => (open ? undefined : setConfirming(null))}
        intent={intent}
        pending={publishMutation.isPending || deleteMutation.isPending}
        onConfirm={async () => {
          const action = confirming;
          setConfirming(null);
          if (action === "delete") await deleteMutation.mutateAsync();
          if (action === "publish") await publishMutation.mutateAsync();
        }}
      />
    </div>
  );
}

function reportFailure(title: string) {
  return (error: unknown) =>
    notify.error(title, {
      description: `Nothing changed. ${
        error instanceof Error ? error.message : "The division grid operation failed."
      } Retry, or reload the page if it keeps failing.`
    });
}
