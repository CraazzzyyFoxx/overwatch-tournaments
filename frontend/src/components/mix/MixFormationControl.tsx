"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";

import { NumberInput } from "@/components/ui/number-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { MixTeamFormation } from "@/services/custom-game.service";

type Formation = { team_formation: MixTeamFormation; draft_pick_seconds: number };

/**
 * How a mix (or a host's new mixes of one game) forms teams: the balancer, or a captain draft on a pick clock.
 *
 * The clock reports every in-range keystroke, for a caller holding a local draft it saves on its own. A caller that
 * writes the server on every change (the mix header) sets `commitOnBlur`: one write when the field is left, not "12"
 * on the way to "120".
 */
export function MixFormationControl({
  value,
  onChange,
  disabled = false,
  commitOnBlur = false,
  idPrefix,
}: Readonly<{
  value: Formation;
  onChange: (next: Formation) => void;
  disabled?: boolean;
  commitOnBlur?: boolean;
  idPrefix: string;
}>) {
  const t = useTranslations("mixes.header");
  // NumberInput reports the clamped value (or null when emptied) right before its onBlur, so this is never stale there.
  const typed = useRef<number | null>(null);
  const commit = () => {
    const next = typed.current;
    if (next != null && next >= 10 && next <= 600 && next !== value.draft_pick_seconds) {
      onChange({ ...value, draft_pick_seconds: next });
    }
  };
  return (
    <span className="flex shrink-0 items-center gap-2">
      <Select
        value={value.team_formation}
        disabled={disabled}
        onValueChange={(next) => onChange({ ...value, team_formation: next as MixTeamFormation })}
      >
        <SelectTrigger id={`${idPrefix}-formation`} aria-label={t("formation")} size="sm" className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="balance">{t("formationBalance")}</SelectItem>
          <SelectItem value="draft">{t("formationDraft")}</SelectItem>
        </SelectContent>
      </Select>
      {value.team_formation === "draft" ? (
        <NumberInput
          id={`${idPrefix}-pick-seconds`}
          integer
          min={10}
          max={600}
          aria-label={t("pickSeconds")}
          title={t("pickSeconds")}
          disabled={disabled}
          value={value.draft_pick_seconds}
          onValueChange={(next) => {
            typed.current = next;
            if (!commitOnBlur) commit();
          }}
          onBlur={commitOnBlur ? commit : undefined}
          size="sm"
          className="w-20 bg-background/50 px-2 tabular-nums"
        />
      ) : null}
    </span>
  );
}
