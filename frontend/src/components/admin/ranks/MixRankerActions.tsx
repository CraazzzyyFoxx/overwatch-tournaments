"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, SlidersHorizontal } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type { WorkspaceRankerUpsert } from "@/types/balancer-admin.types";

type NumericField = Exclude<keyof WorkspaceRankerUpsert, "variant">;

/** Open-scale bounds are whole rank points; the three shape knobs are decimals. */
const FIELDS: ReadonlyArray<{ key: NumericField; integer: boolean }> = [
  { key: "rating_min", integer: true },
  { key: "rating_avg", integer: true },
  { key: "rating_max", integer: true },
  { key: "gravity", integer: false },
  { key: "gate_steepness", integer: false },
  { key: "sigma_init", integer: false }
];

/**
 * The mix ranker's workspace controls on the rank overview: recalculate the
 * hidden ratings from match history, and edit the knobs they are computed with.
 *
 * Both land in the table below (its `hidden` and `effective_mix` layers), so
 * every overview page is invalidated after either write. The page is already
 * gated on `team.update`, the same permission the two writes need.
 */
export function MixRankerActions({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = useTranslations("admin.rankOverview.ranker");
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<WorkspaceRankerUpsert | null>(null);

  const rankerQuery = useQuery({
    queryKey: balancerQueryKeys.workspaceRanker(workspaceId),
    queryFn: () => balancerAdminService.getWorkspaceRanker(workspaceId),
    enabled: settingsOpen
  });

  const openSettings = (open: boolean) => {
    setSettingsOpen(open);
    if (!open) setDraft(null);
  };

  const rebuild = useMutation({
    mutationFn: () => balancerAdminService.rebuildWorkspaceRanker(workspaceId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: balancerQueryKeys.workspaceRanker(workspaceId) });
      void queryClient.invalidateQueries({ queryKey: adminQueryKeys.rank() });
      setConfirmOpen(false);
      notify.success(t("rebuilt", { ratings: result.hidden_ratings, matches: result.matches }));
    },
    onError: (cause) => notify.apiError(cause, { title: t("rebuildError") })
  });

  const save = useMutation({
    mutationFn: (body: WorkspaceRankerUpsert) =>
      balancerAdminService.upsertWorkspaceRanker(workspaceId, body),
    onSuccess: (saved) => {
      queryClient.setQueryData(balancerQueryKeys.workspaceRanker(workspaceId), saved);
      void queryClient.invalidateQueries({ queryKey: adminQueryKeys.rank() });
      openSettings(false);
      notify.success(t("saved"));
    },
    onError: (cause) => notify.apiError(cause, { title: t("saveError") })
  });

  // Every open starts from the stored row: an edit abandoned by closing the
  // dialog must not come back the next time it opens.
  const stored = rankerQuery.data;
  const form: WorkspaceRankerUpsert | null =
    draft ??
    (stored == null
      ? null
      : {
          rating_min: stored.rating_min,
          rating_max: stored.rating_max,
          rating_avg: stored.rating_avg,
          gravity: stored.gravity,
          gate_steepness: stored.gate_steepness,
          sigma_init: stored.sigma_init,
          variant: stored.variant
        });
  const setField = <K extends keyof WorkspaceRankerUpsert>(key: K, value: WorkspaceRankerUpsert[K]) =>
    form != null && setDraft({ ...form, [key]: value });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => openSettings(true)}>
        <SlidersHorizontal aria-hidden className="size-4" />
        {t("settings")}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={rebuild.isPending}
        onClick={() => setConfirmOpen(true)}
      >
        <RefreshCw aria-hidden className="size-4" />
        {rebuild.isPending ? t("rebuilding") : t("rebuild")}
      </Button>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        pending={rebuild.isPending}
        intent={{
          title: t("confirmTitle"),
          description: t("confirmDescription"),
          confirmLabel: t("confirmLabel"),
          tone: "warning"
        }}
        onConfirm={() => rebuild.mutate()}
      />

      <Dialog open={settingsOpen} onOpenChange={openSettings}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("dialogTitle")}</DialogTitle>
            <DialogDescription>
              {t("dialogDescription")}{" "}
              {t.rich("credit", {
                link: (chunks) => (
                  <a
                    href="https://github.com/mixtura-dev/mixtura-ranker"
                    target="_blank"
                    rel="noreferrer"
                    className="underline underline-offset-2"
                  >
                    {chunks}
                  </a>
                )
              })}
            </DialogDescription>
          </DialogHeader>

          {form == null ? (
            <p className="text-sm text-muted-foreground">
              {rankerQuery.isError ? t("loadError") : t("loading")}
            </p>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-2">
                {FIELDS.map(({ key, integer }) => (
                  <div key={key} className="space-y-1">
                    <Label htmlFor={`ranker-${key}`} className="text-xs">
                      {t(`fields.${key}`)}
                    </Label>
                    <NumberInput
                      id={`ranker-${key}`}
                      integer={integer}
                      min={0}
                      value={form[key]}
                      onValueChange={(next) => setField(key, next ?? 0)}
                    />
                  </div>
                ))}
              </div>

              <div className="space-y-1">
                <Label htmlFor="ranker-variant" className="text-xs">
                  {t("fields.variant")}
                </Label>
                <Select
                  value={form.variant}
                  onValueChange={(next) => setField("variant", next as WorkspaceRankerUpsert["variant"])}
                >
                  <SelectTrigger id="ranker-variant" aria-label={t("fields.variant")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="corrected">{t("variants.corrected")}</SelectItem>
                    <SelectItem value="reference">{t("variants.reference")}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">{t("variantHint")}</p>
              </div>

              <p className="text-xs text-muted-foreground">
                {t("hiddenCount", { count: stored?.hidden_ratings ?? 0 })} {t("scaleNote")}
              </p>

              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => openSettings(false)}>
                  {t("cancel")}
                </Button>
                <Button size="sm" onClick={() => save.mutate(form)} disabled={save.isPending}>
                  {save.isPending ? t("saving") : t("save")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
