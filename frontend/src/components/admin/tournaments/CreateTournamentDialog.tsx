"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { GameField } from "@/components/workspace/GameField";
import { notify } from "@/lib/notify";
import { normalizeChallongeSlug } from "@/lib/tournament/challonge";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import adminService from "@/services/admin.service";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Tournament } from "@/types/tournament.types";

type Source = "manual" | "challonge";

/** Each source as a choice card: what it is, and what it leaves for later. */
const SOURCES = [
  { value: "manual", title: "sourceManual", hint: "sourceManualHint" },
  { value: "challonge", title: "sourceChallonge", hint: "sourceChallongeHint" }
] as const satisfies readonly { value: Source; title: string; hint: string }[];

const FORMATIONS = ["balancer", "draft", "registration", "solo"] as const;

/** Visual required marker; `required` on the control carries the semantics. */
const requiredMark = (
  <span aria-hidden className="ml-0.5 text-danger">
    *
  </span>
);

/**
 * "Create tournament": only what a tournament cannot exist without — its game (spec §7.2), where its bracket comes
 * from, a name and dates — plus the team formation, which decides the phases it has. It is created Unpublished;
 * the caller opens its Overview, whose checklist walks the rest of the setup.
 */
export function CreateTournamentDialog({
  workspaceId,
  games,
  defaultGame,
  onClose,
  onCreated
}: Readonly<{
  workspaceId: number;
  /** The area's enabled games. */
  games: DisciplineDescriptor[];
  /** `defaultCreationGame` of the list's game filter. */
  defaultGame: string;
  onClose: () => void;
  onCreated: (tournament: Tournament) => void;
}>) {
  const t = useTranslations("adminTournaments.create");
  const queryClient = useQueryClient();
  const [game, setGame] = useState(defaultGame);
  const [source, setSource] = useState<Source>("manual");
  const [name, setName] = useState("");
  const [challongeSlug, setChallongeSlug] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [teamFormation, setTeamFormation] = useState<string>("balancer");
  const [submitted, setSubmitted] = useState(false);

  const errors: Record<string, string> = {};
  if (source === "manual" && !name.trim()) errors.name = t("validation.nameRequired");
  if (source === "challonge" && !challongeSlug.trim()) errors.challongeSlug = t("validation.challongeRequired");
  if (!startDate || !endDate) errors.dates = t("validation.datesRequired");
  const shownErrors = submitted ? errors : {};

  const create = useMutation({
    mutationFn: async (): Promise<Tournament> => {
      if (source === "manual") {
        return adminService.createTournament({
          workspace_id: workspaceId,
          discipline: game,
          name: name.trim(),
          is_league: false,
          is_hidden: true,
          team_formation: teamFormation,
          start_date: startDate,
          end_date: endDate
        });
      }
      const imported = await adminService.createTournamentWithGroups({
        workspace_id: workspaceId,
        discipline: game,
        challonge_slug: normalizeChallongeSlug(challongeSlug),
        is_league: false,
        start_date: startDate,
        end_date: endDate
      });
      // The import takes neither visibility nor formation. A failure here must not fail the mutation: a retry
      // would import the bracket a second time.
      try {
        return await adminService.updateTournament(imported.id, { is_hidden: true, team_formation: teamFormation });
      } catch {
        notify.warning(t("importHideWarning"), { description: t("importHideDescription") });
        return imported;
      }
    },
    onSuccess: (tournament) => {
      void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() });
      notify.success(t("created"), { description: t("createdDescription") });
      onCreated(tournament);
    },
    onError: (error) => notify.apiError(error, { title: t("createError") })
  });

  return (
    <EntityFormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("title")}
      description={t("description")}
      submitLabel={t("submit")}
      submittingLabel={t("submitting")}
      isSubmitting={create.isPending}
      isDirty={Boolean(name.trim() || challongeSlug.trim() || startDate || endDate)}
      fieldErrors={shownErrors}
      onSubmit={() => {
        setSubmitted(true);
        if (Object.keys(errors).length === 0) create.mutate();
      }}
    >
      {/* The first choice: it decides which fields follow. The cards say what they choose, so the group's name
          is for assistive tech only. */}
      <RadioGroup
        aria-label={t("source")}
        value={source}
        onValueChange={(next) => setSource(next as Source)}
        className="grid-cols-1 sm:grid-cols-2"
      >
        {SOURCES.map(({ value, title, hint }) => {
          const id = `create-tournament-source-${value}`;
          return (
            <FieldLabel key={value} htmlFor={id}>
              <Field orientation="horizontal">
                {/* Named by the title alone; the hint describes it, rather than both reading as one long name. */}
                <RadioGroupItem id={id} value={value} aria-labelledby={`${id}-title`} aria-describedby={`${id}-hint`} />
                <FieldContent>
                  <FieldTitle id={`${id}-title`}>{t(title)}</FieldTitle>
                  <FieldDescription id={`${id}-hint`} size="sm">
                    {t(hint)}
                  </FieldDescription>
                </FieldContent>
              </Field>
            </FieldLabel>
          );
        })}
      </RadioGroup>

      <GameField
        id="create-tournament-game"
        games={games}
        value={game}
        onChange={setGame}
        disabled={games.length < 2}
      />

      {source === "manual" ? (
        <div className="space-y-1.5">
          <Label htmlFor="create-tournament-name">
            {t("name")}
            {requiredMark}
          </Label>
          <Input
            id="create-tournament-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            aria-invalid={shownErrors.name ? true : undefined}
          />
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="create-tournament-challonge">
            {t("challongeSlug")}
            {requiredMark}
          </Label>
          <Input
            id="create-tournament-challonge"
            value={challongeSlug}
            onChange={(event) => setChallongeSlug(event.target.value)}
            placeholder={t("challongePlaceholder")}
            required
            aria-invalid={shownErrors.challongeSlug ? true : undefined}
          />
          <p className="text-xs text-muted-foreground">{t("challongeHelp")}</p>
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="create-tournament-dates">
          {t("dateRange")}
          {requiredMark}
        </Label>
        <DateRangePicker
          id="create-tournament-dates"
          startDate={startDate}
          endDate={endDate}
          onChange={(start, end) => {
            setStartDate(start);
            setEndDate(end);
          }}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="create-tournament-formation">{t("teamFormation")}</Label>
        <Select value={teamFormation} onValueChange={setTeamFormation}>
          <SelectTrigger id="create-tournament-formation">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FORMATIONS.map((formation) => (
              <SelectItem key={formation} value={formation}>
                {t(`formation.${formation}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{t("teamFormationHelp")}</p>
      </div>
    </EntityFormDialog>
  );
}
