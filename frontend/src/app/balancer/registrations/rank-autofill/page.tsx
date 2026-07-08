"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronDown, ChevronUp, Loader2, Search } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { Input } from "@/components/ui/input";
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
  const t = useTranslations();
  const tournamentId = useBalancerTournamentId();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [stages, setStages] = useState(() => defaultRankAutofillStages());
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [addToBalancer, setAddToBalancer] = useState(false);
  const [allowPartial, setAllowPartial] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [chainOpen, setChainOpen] = useState(true);
  const [search, setSearch] = useState("");
  const [mismatchOnly, setMismatchOnly] = useState(false);

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
        throw new Error(t("rankAutofill.noTournamentTitle"));
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
      notify.success(t("rankAutofill.successTitle"), {
        description:
          t("rankAutofill.successDescription", {
            applied: result.applied_registrations,
            roles: result.role_updates,
            skipped: result.skipped_registrations
          }) +
          (result.balancer_additions > 0
            ? t("rankAutofill.successBalancerSuffix", { count: result.balancer_additions })
            : "")
      });
    },
    onError: (error: unknown) => notify.apiError(error, { title: t("rankAutofill.errorTitle") })
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

  // Toggle the currently-visible (filtered) actionable players, preserving any selection outside
  // the current filter.
  const handleToggleAll = (checked: boolean, ids: number[]) =>
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) {
          next.add(id);
        } else {
          next.delete(id);
        }
      }
      return next;
    });

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>{t("rankAutofill.noTournamentTitle")}</AlertTitle>
        <AlertDescription>{t("rankAutofill.noTournamentDescription")}</AlertDescription>
      </Alert>
    );
  }

  const registrationsHref = searchParams.toString()
    ? `/balancer/registrations?${searchParams.toString()}`
    : "/balancer/registrations";

  const preview = previewQuery.data;
  const stats = preview
    ? [
        { label: t("rankAutofill.stats.players"), value: preview.total_registrations, color: "" },
        {
          label: t("rankAutofill.stats.update"),
          value: preview.updatable_registrations,
          color: "text-emerald-300"
        },
        { label: t("rankAutofill.stats.ranks"), value: preview.role_updates, color: "text-emerald-300" },
        {
          label: t("rankAutofill.stats.toBalancer"),
          value: preview.balancer_additions,
          color: "text-cyan-300"
        },
        {
          label: t("rankAutofill.stats.unverified"),
          value: preview.unverified_registrations,
          color: preview.unverified_registrations > 0 ? "text-amber-300" : ""
        },
        {
          label: t("rankAutofill.stats.skipped"),
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
          <h1 className="text-2xl font-semibold tracking-tight">{t("rankAutofill.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("rankAutofill.subtitle")}</p>
        </div>
        <Button variant="outline" asChild>
          <Link href={registrationsHref}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t("rankAutofill.backToRegistrations")}
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">{t("rankAutofill.chainTitle")}</CardTitle>
              <CardDescription>{t("rankAutofill.chainDescription")}</CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              onClick={() => setChainOpen((open) => !open)}
              aria-label={t("rankAutofill.toggleChainAria")}
              aria-expanded={chainOpen}
            >
              {chainOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>
        {chainOpen && (
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
                  aria-label={t("rankAutofill.overwriteAria")}
                />
                <span className="text-xs text-white/65 select-none">{t("rankAutofill.overwrite")}</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={addToBalancer}
                  onCheckedChange={(checked) => setAddToBalancer(checked === true)}
                  disabled={applyMutation.isPending}
                  aria-label={t("rankAutofill.addToBalancerAria")}
                />
                <span className="text-xs text-white/65 select-none">
                  {t("rankAutofill.addToBalancer")}
                </span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={allowPartial}
                  onCheckedChange={(checked) => setAllowPartial(checked === true)}
                  disabled={applyMutation.isPending}
                  aria-label={t("rankAutofill.allowPartialAria")}
                />
                <span className="text-xs text-white/65 select-none">
                  {t("rankAutofill.allowPartial")}
                </span>
              </label>
              {previewQuery.isFetching && (
                <div className="ml-auto flex items-center gap-1.5 text-xs text-white/40">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t("rankAutofill.previewUpdating")}
                </div>
              )}
            </div>
          </CardContent>
        )}
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">{t("rankAutofill.previewTitle")}</CardTitle>
            <CardDescription>{t("rankAutofill.previewDescription")}</CardDescription>
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
        <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/30" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("rankAutofill.searchPlaceholder")}
                className="h-8 pl-8 text-xs"
              />
            </div>
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={mismatchOnly}
                onCheckedChange={(checked) => setMismatchOnly(checked === true)}
                aria-label={t("rankAutofill.mismatchOnlyAria")}
              />
              <span className="text-xs text-white/65 select-none">{t("rankAutofill.mismatchOnly")}</span>
            </label>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {previewQuery.isError ? (
              <Alert variant="destructive">
                <AlertTitle>{t("rankAutofill.previewErrorTitle")}</AlertTitle>
                <AlertDescription>
                  {previewQuery.error instanceof Error
                    ? previewQuery.error.message
                    : t("rankAutofill.previewErrorGeneric")}
                </AlertDescription>
              </Alert>
            ) : (
              <RankAutofillPreviewTables
                preview={previewQuery.data}
                loading={previewQuery.isFetching}
                search={search}
                mismatchOnly={mismatchOnly}
                selectedIds={selectedIds}
                onToggle={handleTogglePlayer}
                onToggleAll={handleToggleAll}
              />
            )}
          </div>
        </CardContent>
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-white/10 px-6 py-3">
          <span className="text-xs text-white/45">
            {t("rankAutofill.selectedCount", { count: selectedIds.size })}
          </span>
          <Button onClick={() => applyMutation.mutate()} disabled={applyDisabled}>
            {applyMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Check className="mr-1.5 h-4 w-4" />
            )}
            {t("rankAutofill.apply", { count: selectedIds.size })}
          </Button>
        </div>
      </Card>
    </div>
  );
}
