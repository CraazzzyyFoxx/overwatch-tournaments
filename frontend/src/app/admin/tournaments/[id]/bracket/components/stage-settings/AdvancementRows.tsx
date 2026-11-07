"use client";

import { useId, type ComponentProps, type ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SettingRow, settingLabelId } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { Stage, StageType } from "@/types/tournament.types";

import { DraftFormatFields } from "../../../components/draft/DraftFormatFields";
import { FeedRuleFields, type FeedField } from "./FeedRuleFields";
import type { StageFeedState } from "./useStageFeed";

const FORMATION_MODES = ["balancer", "draft", "registered", "manual"] as const;

const SectionField: FeedField = ({ id, label, hint, children }: ComponentProps<FeedField>) => (
  <SettingRow htmlFor={id} label={label} hint={hint}>
    {children}
  </SettingRow>
);

/**
 * Where this stage's participants come from, as rows of the General card: the entry that feeds a first stage, or the
 * rule of the filter between it and the stage before, kept in the flow graph. A stage fed by a formation is read
 * through it: the stage before (or the registration), the rule into the formation, and how the formation makes teams.
 * A wiring Bracket cannot express is told in words with a way into Flow, and is never rewritten from here.
 */
export function AdvancementRows({
  stage,
  stageType,
  advancement
}: Readonly<{ stage: Stage; stageType: StageType; advancement: StageFeedState }>) {
  const t = useTranslations("adminBracket.feed");
  const tModes = useTranslations("adminTournament.flow.inspector.modes");
  const ids = useId();
  const { feed, choice, sourceStage, candidates, disabledReason } = advancement;
  if (!feed) return null;

  const formation = feed.kind === "formed" ? feed.formation : null;
  const input = feed.kind === "formed" ? feed.inner : feed;
  const disabled = disabledReason !== null;

  const fedBy = (sources: string[]) => (
    <SettingRow label={t("fedBy")}>
      <span className="text-sm text-foreground">{sources.join(", ")}</span>
    </SettingRow>
  );
  const edit = advancement.formation;
  const formedBy =
    formation && edit ? (
      <>
        <SettingRow
          htmlFor={`${ids}-formed-by`}
          label={t("formedBy")}
          hint={advancement.formationDisabledReason ?? t("formedByHint")}
        >
          <Select
            value={edit.mode}
            disabled={advancement.formationDisabledReason !== null}
            onValueChange={(mode) => advancement.patchFormation({ mode })}
          >
            <SelectTrigger id={`${ids}-formed-by`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FORMATION_MODES.map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {tModes(mode)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingRow>
        {edit.mode === "draft" ? (
          <SettingRow
            stacked
            htmlFor={`${ids}-draft-format`}
            label={t("draftFormat")}
            hint={advancement.formatDisabledReason ?? t("draftFormatHint")}
          >
            <DraftFormatFields
              labelledBy={settingLabelId(`${ids}-draft-format`)}
              value={edit.draft_format}
              rounds={advancement.draftRounds}
              disabled={advancement.formatDisabledReason !== null}
              onChange={(draft_format) => advancement.patchFormation({ draft_format })}
            />
          </SettingRow>
        ) : null}
      </>
    ) : null;
  const rows = (body: ReactNode) => (
    <>
      {body}
      {formedBy}
    </>
  );

  if (input.kind === "entry") return rows(fedBy(input.sources));
  if (input.kind === "none" && formation) return rows(fedBy([formation.name]));

  if (input.kind === "complex") {
    return rows(
      <SettingRow
        label={t("fedBy")}
        hint={`${input.sources.map(({ kind, name }) => `${t(`kinds.${kind}`)} \u201c${name}\u201d`).join(", ")}. ${t("complexHint")}`}
      >
        <Button asChild variant="outline" size="sm">
          <Link href={`/admin/tournaments/${stage.tournament_id}/bracket/flow?node=${stage.node_id}`}>
            {t("editInFlow")}
          </Link>
        </Button>
      </SettingRow>
    );
  }

  // Entry and complex feeds are answered above; only a missing choice or nothing to choose from is left.
  if (!choice || (!formation && candidates.length === 0)) return null;

  // Through a formation the source is the formation's own wiring (its teams and draft hang on it): shown, changed in Flow.
  const source = formation ? (
    <SettingRow label={t("source")} hint={disabledReason ?? t("help")}>
      <span className="text-sm text-foreground">{sourceStage?.name}</span>
    </SettingRow>
  ) : (
    <SettingRow htmlFor={`${ids}-source`} label={t("source")} hint={disabledReason ?? t("help")}>
      <Select
        value={choice.source != null ? String(choice.source) : ""}
        disabled={disabled}
        onValueChange={(value) => advancement.pick(Number(value))}
      >
        <SelectTrigger id={`${ids}-source`}>
          <SelectValue placeholder={t("sourcePick")} />
        </SelectTrigger>
        <SelectContent>
          {candidates.map((candidate) => (
            <SelectItem key={candidate.id} value={String(candidate.node_id)}>
              {candidate.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingRow>
  );

  return rows(
    <>
      {source}
      {sourceStage ? (
        <FeedRuleFields
          ids={ids}
          rule={choice.rule}
          source={sourceStage}
          targetStageType={formation ? null : stageType}
          disabled={disabled}
          Field={SectionField}
          onChange={advancement.patch}
        />
      ) : null}
    </>
  );
}
