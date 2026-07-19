"use client";

import { useEffect, useState } from "react";
import { Loader2, RotateCcw, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { EncounterMapPoolState, MapVetoAction } from "@/types/tournament.types";

import type { VetoSide } from "./veto-model";

interface VetoAdminControlsProps {
  encounterId: number;
  state: EncounterMapPoolState;
  selectedMapId: number | null;
  selectedMapName: string | null;
  onMutated: () => void;
}

/**
 * Workspace-admin overrides: reset the whole session (drop + re-create with
 * seeds re-resolved) and perform a veto step on behalf of either side.
 */
export function VetoAdminControls({
  encounterId,
  state,
  selectedMapId,
  selectedMapName,
  onMutated,
}: VetoAdminControlsProps) {
  const t = useTranslations("encounters.veto.room");
  const defaultSide: VetoSide = state.turn_side ?? "home";
  const defaultAction: MapVetoAction = state.expected_action === "pick" ? "pick" : "ban";
  const [side, setSide] = useState<VetoSide>(defaultSide);
  const [action, setAction] = useState<MapVetoAction>(defaultAction);

  // Follow the live turn: whenever the current step changes, re-point the
  // override controls at the side/action the sequence actually expects.
  useEffect(() => {
    setSide(defaultSide);
    setAction(defaultAction);
  }, [defaultSide, defaultAction, state.current_step_index]);

  const resetMutation = useMutation({
    mutationFn: () => adminService.resetVetoSession(encounterId),
    onSuccess: () => {
      notify.success(t("admin.resetSuccess"));
      onMutated();
    },
    onError: (error) => notify.apiError(error, { title: t("admin.resetFailed") }),
  });

  const actMutation = useMutation({
    mutationFn: (input: { side: VetoSide; map_id: number; action: MapVetoAction }) =>
      adminService.adminVetoAct(encounterId, input),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.actFailed") }),
  });

  const canAct =
    state.session?.status === "active" && !state.is_complete && selectedMapId != null;
  const pending = resetMutation.isPending || actMutation.isPending;

  return (
    <section className="rounded-xl border border-dashed border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[color:var(--aqt-amber)]" aria-hidden />
        <h2 className="text-sm font-semibold">{t("admin.title")}</h2>
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        {state.session?.status === "active" && !state.is_complete ? (
          <>
            <ChoiceGroup
              label={t("admin.sideLabel")}
              options={[
                { value: "home", label: t("side.home") },
                { value: "away", label: t("side.away") },
              ]}
              value={side}
              onChange={setSide}
            />
            <ChoiceGroup
              label={t("admin.actionLabel")}
              options={[
                { value: "ban", label: t("action.ban") },
                { value: "pick", label: t("action.pick") },
              ]}
              value={action}
              onChange={setAction}
            />
            <Button
              size="sm"
              disabled={!canAct || pending}
              onClick={() => {
                if (selectedMapId == null) return;
                actMutation.mutate({ side, map_id: selectedMapId, action });
              }}
            >
              {actMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              {t("admin.confirm")}
              {selectedMapName ? `: ${selectedMapName}` : ""}
            </Button>
            {selectedMapId == null ? (
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("admin.selectMapFirst")}
              </span>
            ) : null}
          </>
        ) : null}

        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button size="sm" variant="destructive" disabled={pending} className="ml-auto">
              {resetMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
              )}
              {t("admin.reset")}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("admin.resetConfirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription>{t("admin.resetConfirmHint")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("captain.cancel")}</AlertDialogCancel>
              <AlertDialogAction onClick={() => resetMutation.mutate()}>
                {t("admin.resetConfirmAction")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </section>
  );
}

function ChoiceGroup<TValue extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: TValue; label: string }[];
  value: TValue;
  onChange: (value: TValue) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <div className="flex gap-1">
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={option.value === value ? "default" : "outline"}
            className={cn("capitalize", option.value === value ? "pointer-events-none" : null)}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
