"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { encounterScopeLabel } from "@/components/admin/encounters/EncounterCells";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { Button } from "@/components/ui/button";
import { SearchableImageSelect } from "@/components/ui/searchable-image-select";
import { Skeleton } from "@/components/ui/skeleton";
import { useBracketRoundLabel, type BracketRoundLabelFormatter } from "@/hooks/useBracketRoundLabel";
import { UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import type { LogBindRequest, LogProcessingRecord } from "@/types/admin.types";
import tournamentService from "@/services/tournament.service";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import type { Encounter } from "@/types/encounter.types";
import { getLogFileName } from "./logs.helpers";
import { mapWithModeName } from "@/lib/catalog/mode";

/** Two encounters of one pair share a name, so the stage and round tell them apart. */
function encounterOptionLabel(encounter: Encounter, formatRound: BracketRoundLabelFormatter) {
  return `${encounter.name} · ${encounterScopeLabel(encounter)} · ${formatRound(encounter.round, UNKNOWN_ROUND_SHAPE)}`;
}

/**
 * Picks the encounter and actual game for a log. An awaiting_link job that carries its document teams
 * binds with the operator's complete team map (and the game's observed revision as the precondition);
 * every other row only attaches a hint and is reprocessed through the queue.
 */
export function AttachLogDialog({
  record,
  encounters,
  pickTournament,
  historyKey,
  workspaceId,
  isPending,
  onAttach,
  onBind,
  onClose
}: Readonly<{
  record: LogProcessingRecord;
  encounters: Encounter[];
  /** The workspace-wide console passes no encounters: the dialog then lets the operator pick a tournament first. */
  pickTournament: boolean;
  /** Realtime stales this key, so the occupancy read below follows the console. */
  historyKey: readonly unknown[];
  workspaceId: number | null;
  isPending: boolean;
  onAttach: (encounterId: number, encounterGameId: number) => void;
  onBind: (request: LogBindRequest) => void;
  onClose: () => void;
}>) {
  const t = useTranslations("adminTournament.logs");
  const tx = useTranslations("adminTournament.logsExtra");
  const formatRound = useBracketRoundLabel();
  // An awaiting or failed job whose stored document teams are known is bound with an explicit team map.
  const bindMode = (record.status === "awaiting_link" || record.status === "failed") && record.teams.length > 0;
  const [value, setValue] = useState(
    record.attached_encounter_id != null ? String(record.attached_encounter_id) : undefined
  );
  const [gameId, setGameId] = useState(
    record.attached_encounter_game_id != null ? String(record.attached_encounter_game_id) : undefined
  );
  // document team key -> encounter.team id, as the operator picked it. Reset with the game.
  // A Map: document keys are arbitrary strings, including `constructor` and `__proto__`.
  const [teamMap, setTeamMap] = useState<ReadonlyMap<string, string>>(new Map());
  // The workspace console has no encounter list: the operator walks tournament -> encounter -> game.
  const [tournamentValue, setTournamentValue] = useState(
    record.tournament_id != null ? String(record.tournament_id) : undefined
  );
  const tournamentId = tournamentValue === undefined ? undefined : Number(tournamentValue);
  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.byWorkspace(workspaceId ?? "global"),
    queryFn: () => tournamentService.getAll(null, workspaceId),
    enabled: pickTournament
  });
  const encountersQuery = useQuery({
    queryKey: adminQueryKeys.logLinkEncounters(workspaceId, tournamentId),
    queryFn: () => encounterService.getAll(1, "", tournamentId!, -1, "id", "asc", workspaceId),
    enabled: pickTournament && tournamentId !== undefined
  });
  const encounterOptions = pickTournament ? (encountersQuery.data?.results ?? []) : encounters;
  const encounterId = value === undefined ? undefined : Number(value);
  const gamesQuery = useQuery({
    queryKey: encounterQueryKeys.detail(encounterId),
    queryFn: () => encounterService.getEncounter(encounterId!),
    enabled: encounterId !== undefined
  });
  const games = gamesQuery.data?.games.filter((game) => game.state !== "cancelled") ?? [];
  const selectedGame = games.find((game) => String(game.id) === gameId);

  // The authoritative read of the target game, never inferred from the paginated history: its revision is the
  // bind precondition and a historical observation is not replaceable at all.
  const observationQuery = useQuery({
    queryKey: [...historyKey, "game-observation", selectedGame?.id],
    queryFn: () => adminService.getGameObservation(selectedGame!.id),
    enabled: bindMode && selectedGame != null,
    gcTime: 0
  });
  const observation = observationQuery.data;
  const revision = observation?.revision ?? null;

  const teamNames = new Map((gamesQuery.data?.teams ?? []).map((team) => [team.id, team.name]));
  const seats = selectedGame?.teams.map((seat) => seat.encounter_team_id) ?? [];
  // Every document key needs its own explicit pick from this game's seats; never read inherited properties.
  const picked = record.teams.map((team) => teamMap.get(team.key));
  const seatIds = new Set(seats.map(String));
  const mapComplete =
    seats.length === record.teams.length &&
    picked.every((seat) => seat != null && seatIds.has(seat)) &&
    new Set(picked).size === picked.length;
  const mapSeatMismatch = bindMode && selectedGame != null && seats.length !== record.teams.length;
  const loadFailed =
    gamesQuery.isError ||
    (bindMode && selectedGame != null && observationQuery.isError) ||
    (pickTournament && (tournamentsQuery.isError || encountersQuery.isError));
  const loading = gamesQuery.isFetching || (bindMode && selectedGame != null && observationQuery.isFetching);
  const canSubmit =
    selectedGame != null &&
    !loading &&
    !loadFailed &&
    !isPending &&
    (!bindMode || (mapComplete && revision != null && !observation?.is_historical));

  const submitLabel = bindMode ? tx("bind") : t("attach");

  return (
    <EntityFormDialog
      open
      onOpenChange={(open) => {
        if (open) return;
        onClose();
      }}
      title={bindMode ? tx("bindTitle") : t("attachTitle")}
      description={
        bindMode
          ? tx("bindDescription", { filename: getLogFileName(record.filename) })
          : t("attachDescriptionWithFile", { filename: getLogFileName(record.filename) })
      }
      onSubmit={() => {
        if (encounterId === undefined || !selectedGame) return;
        if (!bindMode) return onAttach(encounterId, selectedGame.id);
        onBind({
          encounter_game_id: selectedGame.id,
          teams: Object.fromEntries(record.teams.map((team) => [team.key, Number(teamMap.get(team.key))])),
          expected_revision: revision ?? 0
        });
      }}
      submitLabel={submitLabel}
      submittingLabel={submitLabel}
      isSubmitting={isPending}
      submitDisabled={!canSubmit}
      contentClassName="sm:max-w-lg"
    >
      {pickTournament ? (
        <SearchableImageSelect
          value={tournamentValue}
          onValueChange={(next) => {
            setTournamentValue(next);
            setValue(undefined);
            setGameId(undefined);
            setTeamMap(new Map());
          }}
          disabled={isPending}
          ariaLabel={tx("pickTournament")}
          options={(tournamentsQuery.data?.results ?? []).map((tournament) => ({
            value: String(tournament.id),
            label: tournament.name
          }))}
          placeholder={tx("pickTournament")}
          searchPlaceholder={tx("searchTournament")}
        />
      ) : null}
      <SearchableImageSelect
        value={value}
        onValueChange={(next) => {
          setValue(next);
          setGameId(undefined);
          setTeamMap(new Map());
        }}
        disabled={isPending || (pickTournament && tournamentId === undefined)}
        ariaLabel={t("pickEncounter")}
        options={encounterOptions.map((encounter) => ({
          value: String(encounter.id),
          label: encounterOptionLabel(encounter, formatRound)
        }))}
        placeholder={t("pickEncounter")}
        searchPlaceholder={t("searchEncounter")}
      />
      <SearchableImageSelect
        value={selectedGame ? String(selectedGame.id) : undefined}
        onValueChange={(next) => {
          setGameId(next);
          setTeamMap(new Map());
        }}
        options={games.map((game) => ({
          value: String(game.id),
          label: t("gameOption", {
            position: game.position,
            map: mapWithModeName(game.map, game.mode) ?? t("unknownMap"),
            id: game.id
          })
        }))}
        placeholder={t("pickGame")}
        ariaLabel={t("pickGame")}
        searchPlaceholder={t("searchGame")}
        disabled={encounterId === undefined || gamesQuery.isFetching || gamesQuery.isError || isPending}
      />
      {encounterId !== undefined && loading ? (
        <div role="status">
          <span className="sr-only">{t("loadingGames")}</span>
          <Skeleton aria-hidden className="h-4 w-32" />
        </div>
      ) : loadFailed ? (
        <div role="alert" className="space-y-2 text-sm text-danger">
          <p>{t("gamesLoadFailed")}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              if (pickTournament) {
                void tournamentsQuery.refetch();
                if (tournamentId !== undefined) void encountersQuery.refetch();
              }
              if (encounterId !== undefined) void gamesQuery.refetch();
              if (bindMode && selectedGame) void observationQuery.refetch();
            }}
          >
            {t("reloadGames")}
          </Button>
        </div>
      ) : encounterId !== undefined && gamesQuery.isSuccess && games.length === 0 ? (
        <p role="status" className="text-sm text-muted-foreground">{t("noGames")}</p>
      ) : null}
      {bindMode && selectedGame && !loading && !loadFailed ? (
        <fieldset className="space-y-2" disabled={isPending}>
          <legend className="mb-1 text-sm font-medium">{tx("teamMap")}</legend>
          {mapSeatMismatch ? (
            <p role="alert" className="text-sm text-danger">
              {tx("seatMismatch", { seats: seats.length, teams: record.teams.length })}
            </p>
          ) : (
            record.teams.map((team) => (
              <div key={team.key} className="space-y-1">
                <p className="text-xs text-muted-foreground">
                  {tx("logTeam", { position: team.source_position, key: team.key })}
                  {team.participants.length > 0 ? ` · ${team.participants.join(", ")}` : ""}
                </p>
                <SearchableImageSelect
                  value={teamMap.get(team.key)}
                  onValueChange={(next) =>
                    setTeamMap((current) => {
                      const map = new Map(current);
                      if (next) map.set(team.key, next);
                      else map.delete(team.key);
                      return map;
                    })
                  }
                  // A seat already given to another log team is not offered twice.
                  options={seats
                    .filter((seat) => String(seat) === teamMap.get(team.key) || !picked.includes(String(seat)))
                    .map((seat) => ({
                      value: String(seat),
                      label: teamNames.get(seat) ?? `#${seat}`
                    }))}
                  placeholder={tx("pickSeat")}
                  ariaLabel={tx("seatFor", { team: team.key })}
                  searchPlaceholder={tx("searchSeat")}
                />
              </div>
            ))
          )}
          {observation?.is_historical ? (
            <p role="alert" className="text-sm text-danger">{tx("historicalObservation")}</p>
          ) : revision ? (
            <p role="status" className="text-xs text-muted-foreground">
              {tx("willReplace", { revision })}
            </p>
          ) : null}
        </fieldset>
      ) : null}
    </EntityFormDialog>
  );
}
