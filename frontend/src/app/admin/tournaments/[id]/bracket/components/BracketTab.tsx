"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { BRACKET_STAGE_TYPES, type StageProjection } from "@/lib/bracket/projection";
import type { Team } from "@/types/team.types";
import type { Stage } from "@/types/tournament.types";

import { useHubEncountersQuery } from "../../hubQueries";
import { BracketLayoutSection, useBracketTemplateDraft } from "./BracketLayoutSection";
import { BracketPreview } from "./BracketPreview";

type Mode = "view" | "structure";

/**
 * The stage's bracket in one tab: the tree as it is (or would be generated),
 * and — for an elimination stage with no matches yet — its wiring diagram to
 * redraw. One owner for the template draft, so a trip to the view and back
 * keeps it; leaving with it unsaved asks first.
 */
export function BracketTab({
  stage,
  projection,
  teams,
  onBestOfSaved
}: Readonly<{
  stage: Stage;
  projection: StageProjection;
  teams: Team[];
  onBestOfSaved: (saved: Stage) => void;
}>) {
  const t = useTranslations("adminBracket.bracketTab");
  const tLayout = useTranslations("adminBracket.layoutSection");
  const isBracket = BRACKET_STAGE_TYPES.includes(stage.stage_type);
  const encountersQuery = useHubEncountersQuery(stage.tournament_id);
  const hasEncounters = (encountersQuery.data?.results ?? []).some((encounter) => encounter.stage_id === stage.id);
  const template = useBracketTemplateDraft(stage, isBracket && !hasEncounters);
  const [mode, setMode] = useState<Mode>("view");
  const [leaving, setLeaving] = useState(false);
  // Editing the layout is refused once the stage has matches — the same rule as regenerating.
  const editing = mode === "structure" && isBracket && !hasEncounters;

  const switchTo = (next: Mode) => {
    if (next === "view" && template.dirty) setLeaving(true);
    else setMode(next);
  };

  return (
    <div className="space-y-3">
      {isBracket ? (
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            variant="pill"
            size="sm"
            value={editing ? "structure" : "view"}
            onValueChange={(next) => switchTo(next as Mode)}
            aria-label={t("mode")}
          >
            <ToggleGroupItem value="view">{t("view")}</ToggleGroupItem>
            <ToggleGroupItem value="structure" disabled={hasEncounters}>
              {t("structure")}
            </ToggleGroupItem>
          </ToggleGroup>
          {hasEncounters ? <p className="text-xs text-muted-foreground">{tLayout("hasMatches")}</p> : null}
        </div>
      ) : null}

      {editing ? (
        <BracketLayoutSection stage={stage} state={template} />
      ) : (
        <BracketPreview projection={projection} stage={stage} teams={teams} onBestOfSaved={onBestOfSaved} />
      )}

      <ConfirmDialog
        open={leaving}
        onOpenChange={setLeaving}
        intent={{
          title: t("discardTitle"),
          description: t("discardDescription"),
          confirmLabel: t("discardConfirm"),
          tone: "warning"
        }}
        onConfirm={() => {
          template.discard();
          setLeaving(false);
          setMode("view");
        }}
      />
    </div>
  );
}
