"use client";

import { useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { FfaGameResultsDialog, useFfaErrorMessage } from "@/components/admin/ffa/FfaGameResultsDialog";
import FfaLobbyTable from "@/components/ffa/FfaLobbyTable";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type { FfaLobby } from "@/types/ffa.types";
import type { Stage } from "@/types/tournament.types";

import { tabFallback, useHubStagesQuery } from "../../hubQueries";
import { MatchesView } from "../MatchesView";

/**
 * Where an FFA league is refereed.
 *
 * A lobby has no per-match screen to open — the group's table IS the lobby —
 * so everything an organizer does to it happens here: entering a game,
 * correcting one, voiding one, and resizing the series. The table itself is
 * the shared `FfaLobbyTable` the public bracket renders, so what the organizer
 * checks their entry against is literally what a spectator sees.
 */
export default function LobbiesViewPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);

  return (
    <MatchesView tournamentId={tournamentId}>{() => <LobbiesBoard tournamentId={tournamentId} />}</MatchesView>
  );
}

function LobbiesBoard({ tournamentId }: Readonly<{ tournamentId: number }>) {
  const stagesQuery = useHubStagesQuery(tournamentId);
  if (stagesQuery.isPending) return tabFallback;

  const stages = (stagesQuery.data ?? []).filter((stage) => FFA_STAGE_TYPES.includes(stage.stage_type));
  if (stages.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No FFA stages</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This tournament plays duels only. A lobby appears here once a stage of type FFA League has been
          generated.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {stages.map((stage) => (
        <StageLobbies key={stage.id} tournamentId={tournamentId} stage={stage} />
      ))}
    </div>
  );
}

function StageLobbies({ tournamentId, stage }: Readonly<{ tournamentId: number; stage: Stage }>) {
  const lobbiesQuery = useQuery({
    queryKey: tournamentQueryKeys.ffaStage(tournamentId, stage.id),
    queryFn: () => ffaService.getStage(tournamentId, stage.id)
  });
  const lobbies = lobbiesQuery.data ?? [];

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">{stage.name}</h2>
      {lobbiesQuery.isPending ? (
        <Skeleton className="h-56 w-full rounded-xl" />
      ) : lobbiesQuery.isError ? (
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>The lobbies failed to load.</span>
          <Button variant="outline" size="sm" onClick={() => void lobbiesQuery.refetch()}>
            Try again
          </Button>
        </div>
      ) : lobbies.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No lobbies yet — generate the stage to seat its groups.
        </p>
      ) : (
        lobbies.map((lobby) => <LobbyCard key={lobby.encounter_id} lobby={lobby} />)
      )}
    </section>
  );
}

function LobbyCard({ lobby }: Readonly<{ lobby: FfaLobby }>) {
  const [entering, setEntering] = useState<number | null>(null);
  const [voiding, setVoiding] = useState<number | null>(null);

  // Every position the lobby carries a cell for. Normally `1..best_of`, but a
  // lowered games count leaves the results past the new end visible — and
  // voiding one of those is the only way to finish lowering it.
  const positions = Array.from(
    { length: Math.max(lobby.best_of, lobby.rows[0]?.games.length ?? 0, 1) },
    (_, index) => index + 1
  );
  const played = new Set(
    lobby.rows.flatMap((row) => row.games.filter((game) => game.state != null).map((game) => game.position))
  );

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle className="text-base">{lobby.name}</CardTitle>
        {/* Keyed by the length it edits: the lobby refetches after every write,
            and a field seeded once would keep showing the number the organizer
            replaced (or the one another organizer replaced). */}
        <GamesCountForm key={lobby.best_of} lobby={lobby} />
      </CardHeader>
      <CardContent className="space-y-3">
        {lobby.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No teams have been seeded into this lobby yet.</p>
        ) : (
          <>
            <FfaLobbyTable lobby={lobby} />
            <div className="flex flex-wrap items-center gap-2">
              <span className={EYEBROW_CLASS}>Games</span>
              {positions.map((position) => (
                <span key={position} className="flex items-center gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={played.has(position) ? "outline" : "secondary"}
                    onClick={() => setEntering(position)}
                  >
                    {played.has(position) ? `Correct game ${position}` : `Enter game ${position}`}
                  </Button>
                  {played.has(position) ? (
                    <Button type="button" size="sm" variant="ghost" onClick={() => setVoiding(position)}>
                      Void
                    </Button>
                  ) : null}
                </span>
              ))}
            </div>
          </>
        )}
      </CardContent>

      {entering == null ? null : (
        // Keyed by game: the fields are seeded from what that position records,
        // so switching games must start a fresh form rather than reset one.
        <FfaGameResultsDialog
          key={`${lobby.encounter_id}-${entering}`}
          lobby={lobby}
          position={entering}
          open
          onOpenChange={(next) => {
            if (!next) setEntering(null);
          }}
        />
      )}

      {voiding == null ? null : (
        <VoidGameDialog
          key={`${lobby.encounter_id}-void-${voiding}`}
          lobby={lobby}
          position={voiding}
          onClose={() => setVoiding(null)}
        />
      )}
    </Card>
  );
}

/** The series length of ONE lobby. The server refuses to cut below games played. */
function GamesCountForm({ lobby }: Readonly<{ lobby: FfaLobby }>) {
  const queryClient = useQueryClient();
  const describeError = useFfaErrorMessage();
  const [games, setGames] = useState(String(lobby.best_of));

  const mutation = useMutation({
    mutationFn: (value: number) => ffaService.setGamesCount(lobby.encounter_id, value),
    onSuccess: (updated) => {
      notify.success(`${lobby.name} now plays ${updated.best_of} games`);
      void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.ffaAll(lobby.tournament_id) });
    },
    // One message per failure: the translated one below, not that plus the
    // mutation cache's generic validation toast.
    meta: { suppressErrorToast: true },
    onError: (error: unknown) => notify.error(describeError(error))
  });

  // The server takes 1..50 (`FfaGamesCountInput`); cutting below the games
  // already played is the one bound only it can judge, so that stays a 422.
  const parsed = Number(games);
  const valid =
    Number.isInteger(parsed) && parsed >= 1 && parsed <= 50 && parsed !== lobby.best_of;

  return (
    <div className="flex items-center gap-2">
      <label className={EYEBROW_CLASS} htmlFor={`ffa-games-${lobby.encounter_id}`}>
        Games
      </label>
      <Input
        id={`ffa-games-${lobby.encounter_id}`}
        aria-label={`Games in ${lobby.name}`}
        type="number"
        min={1}
        max={50}
        className="w-20"
        value={games}
        onChange={(event) => setGames(event.target.value)}
      />
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={!valid || mutation.isPending}
        onClick={() => mutation.mutate(parsed)}
      >
        Save
      </Button>
    </div>
  );
}

/**
 * Voiding a played game. The position goes back to being unplayed (the partial
 * unique index excludes cancelled games), and the reason is what the audit
 * trail records — the server refuses without one, so this does too.
 */
function VoidGameDialog({
  lobby,
  position,
  onClose
}: Readonly<{ lobby: FfaLobby; position: number; onClose: () => void }>) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const describeError = useFfaErrorMessage();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (value: string) => ffaService.cancelGame(lobby.encounter_id, position, value),
    onSuccess: () => {
      notify.success(`Game ${position} voided`);
      void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.ffaAll(lobby.tournament_id) });
      onClose();
    },
    // Reported inside the dialog; the mutation cache's generic toast would be
    // a second message for the same failure.
    meta: { suppressErrorToast: true },
    onError: (failure: unknown) => setError(describeError(failure))
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = reason.trim();
    if (!trimmed) {
      setError(t("ffa.errors.ffa_reason_required"));
      return;
    }
    setError(null);
    mutation.mutate(trimmed);
  };

  return (
    <EntityFormDialog
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Void game ${position}`}
      description={`${lobby.name} · the position becomes free and can be entered again`}
      onSubmit={handleSubmit}
      submitLabel="Void game"
      isSubmitting={mutation.isPending}
      errorMessage={error ?? undefined}
    >
      <div className="space-y-1">
        <label className={EYEBROW_CLASS} htmlFor={`ffa-void-reason-${lobby.encounter_id}`}>
          Reason
        </label>
        <Input
          id={`ffa-void-reason-${lobby.encounter_id}`}
          aria-label="Reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Why this game does not count"
        />
        <p className="text-xs text-muted-foreground">
          Recorded in the lobby audit trail. The results of this game stop counting toward the standings.
        </p>
      </div>
    </EntityFormDialog>
  );
}
