"use client";

import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import type { LayoutHeader } from "@/components/bracket/layout";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";
import { isSlotRearrangeable, type BracketMatch } from "@/lib/bracket/view";
import { notify } from "@/lib/notify";
import { BEST_OF_OPTIONS, resolveBestOf } from "@/lib/tournament/best-of";
import adminService from "@/services/admin.service";
import type { Encounter } from "@/types/encounter.types";
import type { Stage, StageBestOfConfig } from "@/types/tournament.types";

type BestOfPatch =
  | { kind: "default"; value: number }
  /** `null` = back to the default. */
  | { kind: "round"; round: number; isFinal: boolean; value: number | null };

/**
 * The config after one pick. The final's length is `final`, which outranks its
 * round's own row, so the final header writes `final` and clears that row;
 * "default" clears both.
 */
export function patchBestOf(config: StageBestOfConfig, patch: BestOfPatch): StageBestOfConfig {
  if (patch.kind === "default") return { ...config, default: patch.value };
  const byRound = { ...config.by_round };
  delete byRound[String(patch.round)];
  if (patch.isFinal) return { ...config, by_round: byRound, final: patch.value };
  if (patch.value != null) byRound[String(patch.round)] = patch.value;
  return { ...config, by_round: byRound };
}

/**
 * An elimination bracket's best-of, set on the bracket itself: a default above
 * the tree and a menu on every round header. A pick saves the stage at once
 * and, once matches exist, rewrites them (`apply-best-of`) — after asking, when
 * that changes a match already played, reported or in play.
 *
 * `matches` is what the tree draws (generated or projected); `generated` is the
 * real rows only. The final is the max round of what is drawn — the server's
 * own rule (`apply_best_of_to_existing`, `bracket_preview`).
 */
export function useBracketBestOf({
  stage,
  matches,
  generated,
  onSaved
}: Readonly<{
  stage: Stage;
  matches: BracketMatch[];
  generated: Encounter[];
  onSaved: (saved: Stage) => void;
}>) {
  const t = useTranslations("adminBracket.bracketBestOf");
  const [confirming, setConfirming] = useState<{ next: StageBestOfConfig; count: number } | null>(null);
  const config = stage.best_of;
  const finalRound = Math.max(0, ...matches.map((match) => match.round));

  const mutation = useMutation({
    mutationFn: async (next: StageBestOfConfig) => {
      const saved = await adminService.updateStage(stage.id, { best_of: next });
      if (generated.length > 0) await adminService.applyStageBestOf(stage.id);
      return saved;
    },
    onSuccess: (saved) => {
      setConfirming(null);
      onSaved(saved);
      notify.success(t("saved"));
    },
    onError: (error) => notify.apiError(error, { title: t("saveError") })
  });

  const pick = (patch: BestOfPatch) => {
    const next = patchBestOf(config, patch);
    const count = generated.filter(
      (encounter) =>
        (!isSlotRearrangeable(encounter) || encounter.is_live) &&
        resolveBestOf(next, encounter.round, { isFinal: encounter.round === finalRound }) !== encounter.best_of
    ).length;
    if (count > 0) setConfirming({ next, count });
    else mutation.mutate(next);
  };

  const renderHeaderAction = (header: LayoutHeader): ReactNode => {
    const isFinal = header.round === finalRound;
    const own = isFinal
      ? (config.final ?? config.by_round[String(header.round)])
      : config.by_round[String(header.round)];
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="dashed"
            size="xs"
            disabled={mutation.isPending}
            aria-label={t("roundMenu", { round: header.label })}
            data-round-best-of={header.round}
          >
            {`Bo${resolveBestOf(config, header.round, { isFinal })}`}
            <ChevronDown aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuRadioGroup
            value={own == null ? "default" : String(own)}
            onValueChange={(value) =>
              pick({
                kind: "round",
                round: header.round,
                isFinal,
                value: value === "default" ? null : Number(value)
              })
            }
          >
            <DropdownMenuRadioItem value="default">{t("inherit", { bo: config.default })}</DropdownMenuRadioItem>
            <DropdownMenuSeparator />
            {BEST_OF_OPTIONS.map((n) => (
              <DropdownMenuRadioItem key={n} value={String(n)}>{`Bo${n}`}</DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  const confirmDialog = (
    <ConfirmDialog
      open={confirming !== null}
      onOpenChange={(open) => {
        if (!open) setConfirming(null);
      }}
      intent={{
        title: t("confirmTitle"),
        description: t("confirmDescription", { count: confirming?.count ?? 0 }),
        confirmLabel: t("confirmLabel"),
        tone: "warning"
      }}
      onConfirm={() => {
        if (confirming) mutation.mutate(confirming.next);
      }}
      pending={mutation.isPending}
    />
  );

  return {
    renderHeaderAction,
    setDefault: (value: number) => pick({ kind: "default", value }),
    pending: mutation.isPending,
    confirmDialog
  };
}
