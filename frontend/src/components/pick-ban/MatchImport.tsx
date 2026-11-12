"use client";

import { useId, useState } from "react";
import { AlertTriangle, CheckCircle2, Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { IngestLinks } from "@/components/IngestLinks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { ApiError } from "@/lib/api/error";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import pickBanService from "@/services/pickBan.service";
import type { IngestClient } from "@/types/discipline.types";
import type { MatchImport as MatchImportRow } from "@/types/encounter.types";

/** Refusals a submitter can act on (the match-import routes); anything else is the generic failure. */
const IMPORT_ERROR_CODES = [
  "invalid_external_id",
  "match_already_imported",
  "unsupported_ingestor",
  "match_import_tournament_only"
] as const;
type ImportErrorCode = (typeof IMPORT_ERROR_CODES)[number];

const STATUS_ICON = { pending: Hourglass, done: CheckCircle2, failed: AlertTriangle } as const;
/** A pending import is retried by the stats worker every minute or so; poll while one is. */
const PENDING_POLL_MS = 30_000;

/**
 * Where a match id is filed: a tournament encounter's games (`games` are the positions it may be filed for: one,
 * id or a started search, so the caller can refresh what it changes; `search` is the round's match being looked up
 * by its players, or given up on for `searchError` (while still looking, `searchNextAttemptAt` is when it tries again);
 * `searchable` lets a search that is not looking start again; `ingestClient` adds where to get the game's uploader).
 */
export type MatchImportScope =
  | { encounterId: number; games: ReadonlyArray<{ id: number; position: number }>; admin?: boolean }
  | {
      customGameId: number;
      encounterId: number;
      onSubmitted: () => void;
      search?: "searching" | "not_found" | null;
      searchError?: string | null;
      searchNextAttemptAt?: string | null;
      searchable?: boolean;
      ingestClient?: IngestClient | null;
    };

/**
 * Files a game's match by its id in the game's own records, and lists what was filed: the stats worker fetches it
 * (retrying until the game's API has it) and imports it like an uploaded log. Rendered only for a game of a
 * discipline that declares a match fetcher (`capabilities.match_fetch`). Organizer rows carry the warnings
 * (anonymous participants dropped, a banned character played). A mix round takes statistics only: its result is
 * never touched.
 */
export function MatchImport({ scope }: Readonly<{ scope: MatchImportScope }>) {
  const t = useTranslations("pickBan.room.matchImport");
  const format = useFormatter();
  const inputId = useId();
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<number | null>(null);
  const [externalId, setExternalId] = useState("");
  const { encounterId } = scope;
  const mix = "customGameId" in scope ? scope : null;
  const games = "games" in scope ? scope.games : [];
  const admin = mix != null || ("admin" in scope && scope.admin === true);
  const gameId = games.find((game) => game.id === picked)?.id ?? games[0]?.id ?? null;
  const key = mix
    ? customGameKeys.matchImports(mix.customGameId, encounterId)
    : encounterQueryKeys.matchImports(encounterId, gameId, admin);

  const imports = useQuery({
    queryKey: key,
    queryFn: () =>
      mix
        ? customGameService.listMatchImports(mix.customGameId, encounterId)
        : pickBanService.listMatchImports(encounterId, gameId as number, admin),
    enabled: mix != null || gameId != null,
    refetchInterval: (query) =>
      query.state.data?.some((row) => row.status === "pending") ? PENDING_POLL_MS : false
  });

  const submit = useMutation({
    mutationFn: () =>
      mix
        ? customGameService.importMatch(mix.customGameId, encounterId, externalId.trim())
        : pickBanService.importMatch(encounterId, gameId as number, externalId.trim(), admin),
    onSuccess: () => {
      setExternalId("");
      notify.success(t("submitted"));
      mix?.onSubmitted();
    },
    onError: (error) => {
      const code =
        error instanceof ApiError
          ? error.details
              .map((detail) => detail.code)
              .find((value): value is ImportErrorCode => IMPORT_ERROR_CODES.some((known) => known === value))
          : undefined;
      if (code != null) notify.error(t("failed"), { description: t(`errors.${code}`) });
      else notify.apiError(error, { title: t("failed") });
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key })
  });

  const research = useMutation({
    mutationFn: async () => {
      if (mix) await customGameService.searchMatch(mix.customGameId, encounterId);
    },
    onSuccess: () => {
      notify.success(t("autoSearch.restarted"));
      mix?.onSubmitted();
    },
    onError: (error) => notify.apiError(error, { title: t("autoSearch.restartFailed") })
  });

  if (mix == null && gameId == null) return null;
  const rows = imports.data ?? [];
  // Nothing to look for while a filed id is still coming or already served.
  const canSearch =
    mix?.searchable === true &&
    mix.search !== "searching" &&
    imports.isSuccess &&
    rows.every((row) => row.status === "failed");
  // Why the search is not done, in words: a known code reads in the reader's language, anything else as a generic
  // temporary refusal -- never the source's own text.
  const searchError = mix?.search != null ? mix.searchError : null;
  const reason = !searchError
    ? null
    : searchError === "no_linked_accounts" ||
        searchError === "not_found_in_window" ||
        searchError === "no_match_yet" ||
        searchError === "source_unavailable"
      ? t(`autoSearch.reasons.${searchError}`)
      : searchError.startsWith("ambiguous: ")
        ? t("autoSearch.reasons.ambiguous", { ids: searchError.slice("ambiguous: ".length) })
        : t("autoSearch.reasons.other");
  const nextAttempt =
    mix?.search === "searching" && mix.searchNextAttemptAt
      ? format.dateTime(new Date(mix.searchNextAttemptAt), { hour: "2-digit", minute: "2-digit" })
      : null;

  return (
    <section className="flex flex-col gap-2">
      <form
        className="flex flex-col gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          submit.mutate();
        }}
      >
        <Label htmlFor={inputId}>{t("label")}</Label>
        <div className="flex flex-wrap gap-2">
          {games.length > 1 ? (
            <Select value={String(gameId)} onValueChange={(value) => setPicked(Number(value))}>
              <SelectTrigger size="sm" className="w-auto" aria-label={t("gameLabel")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {games.map((game) => (
                  <SelectItem key={game.id} value={String(game.id)}>
                    {t("game", { position: game.position })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Input
            id={inputId}
            size="sm"
            autoComplete="off"
            className="min-w-0 flex-1"
            value={externalId}
            onChange={(event) => setExternalId(event.target.value)}
          />
          <Button type="submit" size="sm" variant="outline" disabled={externalId.trim() === "" || submit.isPending}>
            {submit.isPending ? <Spinner className="mr-2" /> : null}
            {t("submit")}
          </Button>
        </div>
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t(mix ? "hintMix" : "hint")}</p>
      </form>
      {mix?.search || canSearch ? (
        <div className="flex flex-col items-start gap-1.5">
          {mix?.search ? (
            <p className="text-caption text-[color:var(--aqt-fg-muted)]">
              {t(mix.search === "searching" ? "autoSearch.searching" : "autoSearch.notFound")}
            </p>
          ) : null}
          {reason ? <p className="text-caption text-[color:var(--aqt-fg-dim)]">{reason}</p> : null}
          {nextAttempt ? (
            <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("autoSearch.nextAttempt", { time: nextAttempt })}</p>
          ) : null}
          {mix?.ingestClient && mix.search ? (
            <div className="flex flex-col gap-1 text-caption text-[color:var(--aqt-fg-muted)]">
              <p>{t("autoSearch.ingestHint")}</p>
              <IngestLinks client={mix.ingestClient} />
            </div>
          ) : null}
          {canSearch ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={research.isPending}
              onClick={() => research.mutate()}
            >
              {research.isPending ? <Spinner className="mr-2" /> : null}
              {t(mix?.search === "not_found" ? "autoSearch.again" : "autoSearch.start")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {imports.isError ? (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("loadFailed")}</p>
      ) : rows.length > 0 ? (
        <ul className="flex flex-col gap-1.5" aria-label={t("listLabel")}>
          {rows.map((row) => (
            <ImportRow key={row.id} row={row} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** One filed id: its state, its attempts while it is not done, why it failed, and the organizer's warnings. */
function ImportRow({ row }: Readonly<{ row: MatchImportRow }>) {
  const t = useTranslations("pickBan.room.matchImport");
  const Icon = STATUS_ICON[row.status];
  // A failed fetch is the row's own state and `last_error`; its warning would say it twice.
  const warnings = (row.warnings ?? []).filter((warning) => warning.code !== "fetch_failed");
  return (
    <li className="flex flex-col gap-0.5 text-caption">
      <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-[color:var(--aqt-fg-muted)]">
        <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
        <span className="aqt-tnum font-medium text-[color:var(--aqt-fg)]">{row.external_id}</span>
        <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
        {t(`status.${row.status}`)}
        {row.status !== "done" && row.attempts > 0 ? (
          <>
            <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
            {t("attempts", { count: row.attempts })}
          </>
        ) : null}
      </span>
      {row.last_error ? <span className="text-[color:var(--aqt-fg-dim)]">{row.last_error}</span> : null}
      {warnings.map((warning) => (
        <span key={warning.code} className="flex items-start gap-1.5 text-[color:var(--aqt-amber)]">
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {warning.code === "participants_dropped"
            ? t("warnings.participants_dropped", { count: warning.count ?? 0 })
            : t("warnings.banned_character_played", { characters: (warning.characters ?? []).join(", ") })}
        </span>
      ))}
    </li>
  );
}
