"use client";

import { useId, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { LoaderCircle, Plus } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldSet,
  FieldTitle
} from "@/components/ui/field";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getApiErrorMessage } from "@/lib/api-error";
import { BEST_OF_OPTIONS, DEFAULT_BEST_OF } from "@/lib/best-of";
import { notify } from "@/lib/notify";
import { withReturnTo } from "@/lib/return-to";
import { stageRoundShape } from "@/components/bracket-view.helpers";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import encounterService from "@/services/encounter.service";
import scrimService from "@/services/scrim.service";
import tournamentService from "@/services/tournament.service";
import type { ScrimCreateInput, ScrimPoolInput } from "@/types/scrim.types";

import {
  ALL_ROUNDS_SCOPE,
  TOURNAMENT_SCOPE,
  decodeScope,
  encodeScope,
  pickBanDraftToInput,
  stageRoundOptions
} from "@/app/admin/tournaments/[id]/components/pickBanConfig.helpers";

import {
  ScrimPoolEditor,
  emptyScrimPoolDraft,
  validateScrimPoolDraft,
  type ScrimPoolDraft
} from "./ScrimPoolEditor";

/** Where a room's rules come from. */
type PoolSource = "copy" | "custom";

const POOL_SOURCES: PoolSource[] = ["copy", "custom"];

export function ScrimCreateDialog({
  workspaceId,
  listQueryKey
}: Readonly<{
  workspaceId: number;
  /** Invalidated on success so the new room shows up behind the closing dialog. */
  listQueryKey: readonly unknown[];
}>) {
  const t = useTranslations("scrims.create");
  const tAdmin = useTranslations("pickBan.admin");
  const ids = useId();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [bestOf, setBestOf] = useState(DEFAULT_BEST_OF);
  const [homeName, setHomeName] = useState("");
  const [awayName, setAwayName] = useState("");
  const [source, setSource] = useState<PoolSource>("copy");
  const [copyTournamentId, setCopyTournamentId] = useState<number | null>(null);
  const [copyStageId, setCopyStageId] = useState<number | null>(null);
  const [copyRound, setCopyRound] = useState<number | null>(null);
  const [pool, setPool] = useState<ScrimPoolDraft>(emptyScrimPoolDraft);

  const tournamentsQuery = useQuery({
    queryKey: ["scrims", "tournaments-lookup", workspaceId],
    queryFn: () => tournamentService.lookup(workspaceId),
    enabled: open && source === "copy",
    staleTime: 5 * 60 * 1000
  });
  const stagesQuery = useQuery({
    queryKey: ["scrims", "stages", copyTournamentId],
    queryFn: () => tournamentService.getStages(copyTournamentId as number),
    enabled: open && source === "copy" && copyTournamentId != null
  });
  // Rounds come from the bracket's real encounters rather than a local guess —
  // elimination numbering is not derivable client-side (see `stageRoundOptions`),
  // and a wrong guess would copy a level the source tournament never had.
  const encountersQuery = useQuery({
    queryKey: ["scrims", "encounters", copyTournamentId],
    queryFn: () =>
      encounterService.getAll(1, "", copyTournamentId, -1, "id", "asc", workspaceId, {
        entities: []
      }),
    enabled: open && source === "copy" && copyStageId != null
  });

  const stages = useMemo(
    () => [...(stagesQuery.data ?? [])].sort((left, right) => left.order - right.order),
    [stagesQuery.data]
  );
  const rounds = useMemo(
    () =>
      copyStageId == null ? [] : stageRoundOptions(copyStageId, encountersQuery.data?.results),
    [copyStageId, encountersQuery.data]
  );
  // The same round names the bracket shows, so a copied scope is recognizable.
  const roundLabel = useBracketRoundLabel();
  const roundShape = useMemo(
    () =>
      stageRoundShape(
        copyStageId,
        stages.find((stage) => stage.id === copyStageId)?.stage_type,
        rounds,
        encountersQuery.data?.results
      ),
    [copyStageId, encountersQuery.data, rounds, stages]
  );

  const poolIssues = source === "custom" ? validateScrimPoolDraft(pool, bestOf) : [];
  const namesFilled = label.trim() !== "" && homeName.trim() !== "" && awayName.trim() !== "";
  const canSubmit =
    namesFilled && (source === "copy" ? copyTournamentId != null : poolIssues.length === 0);

  const createMutation = useMutation({
    mutationFn: (data: ScrimCreateInput) => scrimService.createRoom(data),
    onSuccess: async (room) => {
      await queryClient.invalidateQueries({ queryKey: listQueryKey });
      notify.success(t("created"));
      setOpen(false);
      // Straight into the room: creating one is how a captain starts a veto, and
      // the list is one back-step away thanks to the return-to param.
      router.push(withReturnTo(`/scrims/${room.token}`, "/scrims"));
    },
    // Not `notify.apiError(…, { title })`: an overriding title would bury the
    // server's message, and the active-room cap is only ever explained there
    // (the ceiling is a `Settings` row an admin can raise without a deploy).
    onError: (error) => notify.error(getApiErrorMessage(error, t("failed")))
  });

  const submit = () => {
    const poolInput: ScrimPoolInput =
      source === "copy"
        ? {
            source: "copy",
            tournament_id: copyTournamentId as number,
            stage_id: copyStageId,
            round: copyStageId == null ? null : copyRound
          }
        : {
            source: "custom",
            // `stage_id`/`round` are stripped: the room's own stage does not
            // exist yet, and the server pins both.
            configs: [pool.map, ...(pool.hero == null ? [] : [pool.hero])].map((draft) => {
              const {
                stage_id: _stageId,
                round: _round,
                ...config
              } = pickBanDraftToInput(draft, bestOf);
              return config;
            })
          };

    createMutation.mutate({
      workspace_id: workspaceId,
      label: label.trim(),
      best_of: bestOf,
      home_team_name: homeName.trim(),
      away_team_name: awayName.trim(),
      pool: poolInput
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden className="size-4" />
          {t("open")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <FieldSet disabled={createMutation.isPending}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`${ids}-label`}>{t("labelLabel")}</FieldLabel>
              <Input
                id={`${ids}-label`}
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder={t("labelPlaceholder")}
                maxLength={120}
              />
              <FieldDescription>{t("labelHint")}</FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor={`${ids}-home`}>{t("homeLabel")}</FieldLabel>
                <Input
                  id={`${ids}-home`}
                  value={homeName}
                  onChange={(event) => setHomeName(event.target.value)}
                  placeholder={t("homePlaceholder")}
                  maxLength={120}
                />
                <FieldDescription>{t("homeHint")}</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor={`${ids}-away`}>{t("awayLabel")}</FieldLabel>
                <Input
                  id={`${ids}-away`}
                  value={awayName}
                  onChange={(event) => setAwayName(event.target.value)}
                  placeholder={t("awayPlaceholder")}
                  maxLength={120}
                />
                <FieldDescription>{t("awayHint")}</FieldDescription>
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor={`${ids}-best-of`}>{t("bestOfLabel")}</FieldLabel>
              <Select value={String(bestOf)} onValueChange={(value) => setBestOf(Number(value))}>
                <SelectTrigger id={`${ids}-best-of`} className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BEST_OF_OPTIONS.map((option) => (
                    <SelectItem key={option} value={String(option)}>
                      {t("bestOfValue", { count: option })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldDescription>{t("bestOfHint")}</FieldDescription>
            </Field>

            <Field>
              <FieldTitle className="text-sm">{t("poolSection")}</FieldTitle>
              <FieldDescription>{t("poolSectionHint")}</FieldDescription>
              <FilterChipGroup label={t("poolSection")}>
                {POOL_SOURCES.map((option) => (
                  <FilterChip
                    key={option}
                    active={source === option}
                    onClick={() => setSource(option)}
                  >
                    {option === "copy" ? t("sourceCopy") : t("sourceCustom")}
                  </FilterChip>
                ))}
              </FilterChipGroup>
            </Field>

            {source === "copy" ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Field>
                  <FieldLabel htmlFor={`${ids}-tournament`}>{t("tournamentLabel")}</FieldLabel>
                  <Select
                    value={copyTournamentId == null ? undefined : String(copyTournamentId)}
                    onValueChange={(value) => {
                      setCopyTournamentId(Number(value));
                      setCopyStageId(null);
                      setCopyRound(null);
                    }}
                  >
                    <SelectTrigger id={`${ids}-tournament`}>
                      <SelectValue placeholder={t("tournamentPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {(tournamentsQuery.data ?? []).map((tournament) => (
                        <SelectItem key={tournament.id} value={String(tournament.id)}>
                          {tournament.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field data-disabled={copyTournamentId == null}>
                  <FieldLabel htmlFor={`${ids}-stage`}>{t("stageLabel")}</FieldLabel>
                  <Select
                    value={encodeScope(copyStageId)}
                    disabled={copyTournamentId == null || stagesQuery.isPending}
                    onValueChange={(value) => {
                      setCopyStageId(decodeScope(value));
                      setCopyRound(null);
                    }}
                  >
                    <SelectTrigger id={`${ids}-stage`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={TOURNAMENT_SCOPE}>{t("stageWhole")}</SelectItem>
                      {stages.map((stage) => (
                        <SelectItem key={stage.id} value={encodeScope(stage.id)}>
                          {stage.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field data-disabled={copyStageId == null}>
                  <FieldLabel htmlFor={`${ids}-round`}>{t("roundLabel")}</FieldLabel>
                  <Select
                    value={copyRound == null ? ALL_ROUNDS_SCOPE : String(copyRound)}
                    disabled={copyStageId == null || encountersQuery.isPending}
                    onValueChange={(value) =>
                      setCopyRound(value === ALL_ROUNDS_SCOPE ? null : Number(value))
                    }
                  >
                    <SelectTrigger id={`${ids}-round`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_ROUNDS_SCOPE}>{t("roundAll")}</SelectItem>
                      {rounds.map((round) => (
                        <SelectItem key={round} value={String(round)}>
                          {roundLabel(round, roundShape)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            ) : (
              <ScrimPoolEditor
                pool={pool}
                bestOf={bestOf}
                disabled={createMutation.isPending}
                onChange={setPool}
              />
            )}

            {poolIssues.length > 0 ? (
              <Alert variant="destructive">
                <AlertDescription>
                  <p className="font-medium">{t("poolInvalid")}</p>
                  <ul className="mt-1 list-inside list-disc">
                    {poolIssues.map(({ kind, issue }) => (
                      <li key={`${kind}-${issue.key}`}>
                        {t(kind === "map" ? "issueMap" : "issueHero", {
                          issue: tAdmin(`validation.${issue.key}`, issue.values)
                        })}
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            ) : null}
          </FieldGroup>
        </FieldSet>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} disabled={!canSubmit || createMutation.isPending}>
            {createMutation.isPending ? (
              <LoaderCircle aria-hidden className="size-4 animate-spin" />
            ) : null}
            {t("submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
