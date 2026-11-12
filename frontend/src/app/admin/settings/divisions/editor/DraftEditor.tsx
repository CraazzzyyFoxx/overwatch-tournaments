"use client";

import { useCallback, useMemo, useReducer, useState } from "react";
import { useTranslations } from "next-intl";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { ConfirmDialog, type ConfirmIntent } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { SaveBar } from "@/components/kit/SaveBar";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useFilePicker } from "@/components/ui/file-button";
import { useQueryParams } from "@/hooks/useQueryParams";
import type { DisciplineCapabilities } from "@/types/discipline.types";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type {
  DivisionGridActivationReadiness,
  DivisionGridVersion
} from "@/types/workspace.types";

import { VERSION_PILL, versionState } from "../versionStatus";
import { autoMap, unresolvedRows, type MappingChoices } from "./autoMap";
import { ChangesView } from "./ChangesView";
import { DivisionsTable } from "./DivisionsTable";
import { ImpactColumn } from "./ImpactColumn";
import { LadderColumn } from "./LadderColumn";
import { MappingsView } from "./MappingsView";
import { publishChecks, readyToPublish } from "./publishChecks";
import {
  bandsCoverLadder,
  bandsFromTiers,
  bandsMissingCrest,
  describeEdits,
  diffBands,
  draftReducer,
  initDraftState,
  scaleOf,
  type Band,
  type Ladder,
  type Scale
} from "./draftReducer";
import { DraftEditorActions } from "./draft-editor/DraftEditorActions";
import { useDraftMutations } from "./draft-editor/useDraftMutations";
import { useMappingSources } from "./draft-editor/useMappingSources";

/** The right rail becomes a sub-tab below this width (F12 ·8). */
const RAIL_MEDIA_QUERY = "(min-width: 1280px)";

const TAB_KEYS = ["divisions", "changes", "mappings", "impact"] as const;
type TabKey = (typeof TAB_KEYS)[number];

export interface DraftEditorProps {
  workspaceId: number;
  /** The loaded grid's own discipline — never the browsing choice. */
  discipline: string;
  capabilities: DisciplineCapabilities;
  /** That discipline's native ladder from its metadata; `null` when it declares none. */
  ladder: Ladder | null;
  version: DivisionGridVersion;
  /** The parent version's bands; empty when this version has no parent. */
  base: Band[];
  /** The parent's name ("v3"); read only alongside a non-empty `base`. */
  baseLabel: string;
  readiness: DivisionGridActivationReadiness | null;
  activeVersionId: number | null;
  editable: boolean;
  canPublish: boolean;
  canDelete: boolean;
  /**
   * Mapping picks made before a save that could not store them — carried into
   * the next mount so an incomplete mapping does not lose its decisions.
   */
  initialChoices?: MappingChoices;
  /**
   * Re-mounts this editor from the cache. Both "saved" and "discard my edits"
   * are the same thing to a reducer holding a snapshot stack: throw it away and
   * read the version again. `carry` seeds the next mount's mapping picks.
   */
  onReload: (carry?: MappingChoices) => void;
}

/**
 * The draft division-grid editor (F12): ladder on the left, three views in the
 * middle, impact on the right, one save bar underneath.
 *
 * Everything structural goes through `draftReducer`, so this component owns no
 * band arithmetic — only which view is open, what has been chosen in Mappings,
 * and the four requests (save, publish, activate, delete — `useDraftMutations`).
 *
 * A published or active version opens here read-only: a version another
 * tournament may already have been played on is immutable by design, and the
 * way forward is a new draft cloned from it.
 */
export function DraftEditor({
  workspaceId,
  discipline,
  capabilities,
  ladder,
  version,
  base,
  baseLabel,
  readiness,
  activeVersionId,
  editable,
  canPublish,
  canDelete,
  initialChoices,
  onReload
}: Readonly<DraftEditorProps>) {
  const t = useTranslations("adminSettings.divisions");
  // The game's short name ("OW", "LoL") for the copy that names its ladder; the code until descriptors load.
  const game = useGameDescriptors().get(discipline)?.short_name || discipline;
  const { searchParams, setParams } = useQueryParams();
  const [state, dispatch] = useReducer(
    draftReducer,
    { ladder, tiers: version.tiers, base },
    (seed) =>
      initDraftState(
        seed.ladder,
        bandsFromTiers(seed.ladder, seed.tiers),
        scaleOf(seed.ladder, seed.tiers),
        seed.base
      )
  );
  const [manualChoice, setManualChoice] = useState<MappingChoices>(() => initialChoices ?? {});
  const [confirming, setConfirming] = useState<"publish" | "delete" | "scale" | null>(null);
  const [iconTarget, setIconTarget] = useState<number | null>(null);
  // What the ladder draws for a version that stores no native link is the backend's
  // rank-range fallback, not a decision anyone made — the column says so.
  const implicitLinks = !version.tiers.some(
    (tier) => tier.native_rank_min != null && tier.native_rank_max != null
  );

  const isWide = useMediaQuery(RAIL_MEDIA_QUERY, true);

  const sources = readiness?.sources ?? [];
  const tiersDirty = state.history.length > 0;
  // A mapping pick is an edit too: without it counting, a draft whose tiers are
  // saved could never store the decisions its Mappings tab asks for.
  const pickedCount = Object.keys(manualChoice).length;
  const dirty = tiersDirty || pickedCount > 0;
  // Mapping rules key on target tier ids, so an unsaved band cannot be a target.
  const mappable = state.bands.every((band) => band.id !== undefined);

  const { mappingSources, chosen, loading: sourcesLoading } = useMappingSources(
    sources,
    version.id,
    manualChoice
  );

  const unresolvedMappings = useMemo(
    () =>
      mappingSources.reduce(
        (total, source) =>
          total +
          unresolvedRows(autoMap(ladder, source.tiers, state.bands), chosen, state.bands).length,
        0
      ),
    [chosen, ladder, mappingSources, state.bands]
  );

  const checks = publishChecks({
    ladder,
    bands: state.bands,
    scale: state.scale,
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

  const { saveMutation, publishMutation, activateMutation, deleteMutation, iconMutation, cloneToDraft } =
    useDraftMutations({
      workspaceId,
      discipline,
      ladder,
      version,
      bands: state.bands,
      tiersDirty,
      sources,
      mappingSources,
      chosen,
      manualChoice,
      dispatch,
      onReload
    });

  const { input: iconInput, open: openIconPicker } = useFilePicker({
    accept: "image/png,image/webp,image/svg+xml",
    onFiles: ([file]) => {
      if (iconTarget !== null) iconMutation.mutate({ bandIndex: iconTarget, file });
    }
  });
  const onPickIcon = useCallback(
    (bandIndex: number) => {
      setIconTarget(bandIndex);
      openIconPicker();
    },
    [openIconPicker]
  );

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
    { key: "divisions", label: t("tabs.divisions"), href: tabHref("divisions") },
    {
      key: "changes",
      label: t("tabs.changes"),
      href: tabHref("changes"),
      badge: changeCount || undefined
    },
    {
      key: "mappings",
      label: t("tabs.mappings"),
      href: tabHref("mappings"),
      badge: unresolvedMappings || undefined
    },
    {
      key: "impact",
      label: t("tabs.impact"),
      href: tabHref("impact"),
      hidden: isWide
    }
  ];

  const pill = VERSION_PILL[versionState(version, activeVersionId)];
  const intent: ConfirmIntent =
    confirming === "delete"
      ? {
          title: t("editorDetails.discardTitle", { version: version.version }),
          description: t("editorDetails.discardDescription"),
          confirmLabel: t("editor.discardDraft"),
          tone: "danger"
        }
      : confirming === "scale"
        ? {
            title: t("editor.followLadderTitle", { game }),
            description: t("editorDetails.followDescription"),
            confirmLabel: t("editor.followLadder"),
            tone: "warning"
          }
        : {
            title: t("editorDetails.publishTitle", { version: version.version }),
            description: t("editorDetails.publishDescription"),
            confirmLabel: t("editor.publishVersion", { version: version.version }),
            tone: "warning"
          };

  const changeScale = (next: Scale) => {
    // Leaving the ladder keeps every number; following it rewrites them.
    if (next === "ladder") setConfirming("scale");
    else dispatch({ type: "setScale", scale: next });
  };

  return (
    <div className="flex flex-col gap-4">
      <EntityHubHeader
        backHref="/admin/settings/divisions"
        title={version.label}
        status={pill ? { label: t(pill.key), tone: pill.tone } : undefined}
        meta={[
          `v${version.version}`,
          base.length > 0 ? t("editorDetails.createdFrom", { base: baseLabel }) : null,
          t("divisionCount", { count: state.bands.length }),
          state.scale === "ladder" ? t("editorDetails.followRanges", { game }) : t("editorDetails.customScale")
        ]}
        actions={
          <DraftEditorActions
            version={version}
            activeVersionId={activeVersionId}
            editable={editable}
            canPublish={canPublish}
            canDelete={canDelete}
            canUndo={tiersDirty}
            publishable={publishable}
            publishing={publishMutation.isPending}
            activationReady={readiness?.is_ready === true}
            activating={activateMutation.isPending}
            onUndo={() => dispatch({ type: "undo" })}
            onDiscard={() => setConfirming("delete")}
            onPublish={() => setConfirming("publish")}
            onActivate={() => activateMutation.mutate()}
            onClone={cloneToDraft}
          />
        }
      />

      {!editable ? (
        <p className="text-caption text-muted-foreground">
          {version.status === "draft"
            ? t("editorDetails.readOnlyDraft")
            : t("editorDetails.readOnlyPublished")}
        </p>
      ) : null}

      {iconInput}

      <div
        className={cn(
          "grid items-start gap-4",
          ladder ? "xl:grid-cols-[272px_minmax(0,1fr)_250px]" : "xl:grid-cols-[minmax(0,1fr)_250px]"
        )}
      >
        {ladder ? (
          <LadderColumn
            ladder={ladder}
            game={game}
            bands={state.bands}
            scale={state.scale}
            selectedSlug={selectedSlug}
            editable={editable}
            implicitLinks={implicitLinks && !tiersDirty}
            onSelect={(slug) => setParams({ band: slug })}
            dispatch={dispatch}
          />
        ) : null}

        <div className="flex min-w-0 flex-col gap-3">
          <LinkTabs
            items={tabs}
            activeKey={activeTab}
            level={2}
            ariaLabel={t("editor.views")}
          />

          {activeTab === "divisions" ? (
            <DivisionsTable
              bands={state.bands}
              scale={state.scale}
              discipline={discipline}
              capabilities={capabilities}
              ladder={ladder}
              game={game}
              editable={editable}
              selectedSlug={selectedSlug}
              onSelect={(slug) => setParams({ band: slug })}
              dispatch={dispatch}
              onPickIcon={onPickIcon}
              onScaleChange={changeScale}
              canFollowLadder={ladder !== null && bandsCoverLadder(ladder, state.bands)}
            />
          ) : null}

          {activeTab === "changes" ? (
            <ChangesView ladder={ladder} base={state.base} bands={state.bands} baseLabel={baseLabel} />
          ) : null}

          {activeTab === "mappings" ? (
            <MappingsView
              ladder={ladder}
              targetLabel={`v${version.version}`}
              bands={state.bands}
              sources={mappingSources}
              chosen={chosen}
              onChoose={(sourceTierId, choice) =>
                setManualChoice((current) => ({ ...current, [sourceTierId]: choice }))
              }
              editable={editable}
              mappable={mappable}
              loading={sourcesLoading}
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
          primaryLabel={t("editor.saveDraft")}
          summary={t("impact.editCount", { count: state.history.length + pickedCount })}
          onDiscard={() => onReload()}
          onSave={() => {
            const crestless = bandsMissingCrest(ladder, state.bands);
            if (crestless.length > 0) {
              notify.error(t("errors.crestRequired"), {
                description: t("errors.crestRequiredDescription", {
                  names: crestless.map((band) => band.name).join(", ")
                })
              });
              return;
            }
            saveMutation.mutate();
          }}
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
          if (action === "scale") dispatch({ type: "setScale", scale: "ladder" });
          if (action === "delete") await deleteMutation.mutateAsync();
          if (action === "publish") await publishMutation.mutateAsync();
        }}
      />
    </div>
  );
}
