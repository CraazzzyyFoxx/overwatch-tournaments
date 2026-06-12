"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Loader2 } from "lucide-react";

import {
  defaultRankAutofillStages,
  moveStageBySource,
  setStageEnabled,
  setStageLookback
} from "@/app/balancer/components/rank-autofill-stages";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  RegistrationRankAutofillRequest,
  RegistrationRankAutofillResponse
} from "@/types/balancer-admin.types";

import { RankAutofillPreviewTables } from "./_components/RankAutofillPreviewTables";
import { RankAutofillStageList } from "./_components/RankAutofillStageList";

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

export default function RankAutofillPage() {
  const tournamentId = useBalancerTournamentId();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [stages, setStages] = useState(() => defaultRankAutofillStages());
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [addToBalancer, setAddToBalancer] = useState(false);
  const [allowPartial, setAllowPartial] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const previewRequest = useMemo<RegistrationRankAutofillRequest>(
    () => ({
      overwrite_existing: overwriteExisting,
      add_to_balancer: addToBalancer,
      allow_partial: allowPartial,
      stages
    }),
    [overwriteExisting, addToBalancer, allowPartial, stages]
  );
  // Debounce so dragging / typing the lookback inputs doesn't fire a preview per keystroke.
  const debouncedRequest = useDebouncedValue(previewRequest, 300);

  const previewQuery = useQuery({
    queryKey: ["balancer-admin", "rank-autofill-preview", tournamentId, debouncedRequest],
    queryFn: () =>
      balancerAdminService.previewRegistrationRankAutofill(tournamentId as number, debouncedRequest),
    enabled: tournamentId !== null,
    placeholderData: keepPreviousData
  });

  // Pre-select the actionable players whenever a fresh preview arrives. Done as a render-time
  // sync (guarded by a stored reference) rather than an effect, per the React "adjusting state
  // when data changes" pattern — avoids cascading renders.
  const [syncedPreview, setSyncedPreview] = useState<RegistrationRankAutofillResponse>();
  if (previewQuery.data && previewQuery.data !== syncedPreview) {
    setSyncedPreview(previewQuery.data);
    setSelectedIds(
      new Set(
        previewQuery.data.players
          .filter((player) => player.status === "will_update")
          .map((player) => player.registration_id)
      )
    );
  }

  const applyMutation = useMutation({
    mutationFn: () => {
      if (!tournamentId) {
        throw new Error("Сначала выберите турнир");
      }
      return balancerAdminService.applyRegistrationRankAutofill(tournamentId, {
        ...previewRequest,
        registration_ids: Array.from(selectedIds)
      });
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registrations", tournamentId]
      });
      await previewQuery.refetch();
      notify.success("Ранги проставлены", {
        description:
          `${result.applied_registrations} игрок(ов), ${result.role_updates} ранг(ов) обновлено. ` +
          `Пропущено: ${result.skipped_registrations}.` +
          (result.balancer_additions > 0 ? ` ${result.balancer_additions} → balancer.` : "")
      });
    },
    onError: (error: unknown) => notify.apiError(error, { title: "Не удалось проставить ранги" })
  });

  const handleToggleStage = (source: Parameters<typeof setStageEnabled>[1], enabled: boolean) =>
    setStages((current) => setStageEnabled(current, source, enabled));
  const handleReorderStage = (
    activeSource: Parameters<typeof moveStageBySource>[1],
    overSource: Parameters<typeof moveStageBySource>[2]
  ) => setStages((current) => moveStageBySource(current, activeSource, overSource));
  const handleLookbackChange = (source: Parameters<typeof setStageLookback>[1], value: number | null) =>
    setStages((current) => setStageLookback(current, source, value));

  const handleTogglePlayer = (registrationId: number, checked: boolean) =>
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(registrationId);
      } else {
        next.delete(registrationId);
      }
      return next;
    });

  const handleToggleAll = (checked: boolean) => {
    const updatable = (previewQuery.data?.players ?? [])
      .filter((player) => player.status === "will_update" || player.status === "applied")
      .map((player) => player.registration_id);
    setSelectedIds(checked ? new Set(updatable) : new Set());
  };

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Выберите турнир</AlertTitle>
        <AlertDescription>
          Выберите турнир в сайдбаре, прежде чем настраивать autofill рангов.
        </AlertDescription>
      </Alert>
    );
  }

  const registrationsHref = searchParams.toString()
    ? `/balancer/registrations?${searchParams.toString()}`
    : "/balancer/registrations";

  const preview = previewQuery.data;
  const stats = preview
    ? [
        { label: "Игроки", value: preview.total_registrations, color: "" },
        { label: "Обновить", value: preview.updatable_registrations, color: "text-emerald-300" },
        { label: "Ранги", value: preview.role_updates, color: "text-emerald-300" },
        { label: "→ Balancer", value: preview.balancer_additions, color: "text-cyan-300" },
        {
          label: "Не подтв.",
          value: preview.unverified_registrations,
          color: preview.unverified_registrations > 0 ? "text-amber-300" : ""
        },
        {
          label: "Пропуск",
          value: preview.skipped_registrations,
          color: preview.skipped_registrations > 0 ? "text-orange-300" : ""
        }
      ]
    : [];

  const applyDisabled = applyMutation.isPending || previewQuery.isFetching || selectedIds.size === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Autofill рангов</h1>
          <p className="text-sm text-muted-foreground">
            Настройте цепочку источников и точечно выберите игроков для обновления.
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link href={registrationsHref}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            К регистрациям
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Цепочка источников</CardTitle>
          <CardDescription>
            Перетащите для порядка приоритета, отключите ненужные источники и при необходимости
            ограничьте давность (турниры для истории/аналитики, дни для OW).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <RankAutofillStageList
            stages={stages}
            disabled={applyMutation.isPending}
            onReorder={handleReorderStage}
            onToggle={handleToggleStage}
            onLookbackChange={handleLookbackChange}
          />

          <div className="flex flex-wrap items-center gap-4 border-t border-white/10 pt-3">
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={overwriteExisting}
                onCheckedChange={(checked) => setOverwriteExisting(checked === true)}
                disabled={applyMutation.isPending}
                aria-label="Перезаписывать существующие ранги"
              />
              <span className="text-xs text-white/65 select-none">Перезаписывать существующие</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={addToBalancer}
                onCheckedChange={(checked) => setAddToBalancer(checked === true)}
                disabled={applyMutation.isPending}
                aria-label="Перемещать подходящих в balancer"
              />
              <span className="text-xs text-white/65 select-none">Перемещать в balancer</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={allowPartial}
                onCheckedChange={(checked) => setAllowPartial(checked === true)}
                disabled={applyMutation.isPending}
                aria-label="Частичное применение"
              />
              <span className="text-xs text-white/65 select-none">
                Частично (заполнять найденные роли, даже если не все найдены)
              </span>
            </label>
            {previewQuery.isFetching && (
              <div className="ml-auto flex items-center gap-1.5 text-xs text-white/40">
                <Loader2 className="h-3 w-3 animate-spin" />
                Обновление превью…
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">Превью</CardTitle>
            <CardDescription>Приоритетный fallback по ролям. Только главный BattleTag.</CardDescription>
          </div>
          {preview && (
            <div className="flex shrink-0 items-center divide-x divide-white/10 rounded-lg border border-white/10 bg-white/[0.03]">
              {stats.map(({ label, value, color }) => (
                <div key={label} className="px-3 py-2 text-center">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-white/35">
                    {label}
                  </div>
                  <div className={cn("text-base font-semibold tabular-nums", color || "text-white/80")}>
                    {value}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardHeader>
        <CardContent className="min-h-0 flex-1 overflow-y-auto">
          {previewQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Не удалось загрузить превью</AlertTitle>
              <AlertDescription>
                {previewQuery.error instanceof Error ? previewQuery.error.message : "Ошибка запроса"}
              </AlertDescription>
            </Alert>
          ) : (
            <RankAutofillPreviewTables
              preview={previewQuery.data}
              loading={previewQuery.isFetching}
              selectedIds={selectedIds}
              onToggle={handleTogglePlayer}
              onToggleAll={handleToggleAll}
            />
          )}
        </CardContent>
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-white/10 px-6 py-3">
          <span className="text-xs text-white/45">Выбрано игроков: {selectedIds.size}</span>
          <Button onClick={() => applyMutation.mutate()} disabled={applyDisabled}>
            {applyMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Check className="mr-1.5 h-4 w-4" />
            )}
            Применить к {selectedIds.size}
          </Button>
        </div>
      </Card>
    </div>
  );
}
