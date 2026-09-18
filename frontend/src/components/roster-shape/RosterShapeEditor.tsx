"use client";

import { useId, useState } from "react";
import { Lock, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import FlexIcon from "@/components/icons/FlexIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { EYEBROW_CLASS, TONE_CLASS } from "@/components/admin/tone";
import { cn } from "@/lib/utils";
import { ROLE_ACCENT, getRoleIconName } from "@/lib/roles";
import {
  ROSTER_SLOT_CODES,
  orderSlotCodes,
  isRoleSlotCode,
  slotsTotal,
  type RosterShape,
  type RosterSlotCode,
  type RosterSlotMap
} from "@/lib/roster-shape";

import {
  MAX_SLOT_COUNT,
  ROSTER_SHAPE_MODES,
  draftRoundsPreview,
  initialSelection,
  payloadTotalError,
  previewSlotRows,
  selectMode,
  setSlotCount,
  slotsPayload,
  type RosterShapeSelection
} from "./roster-shape-editor.model";

/**
 * Role hues, straight off the design-book role tokens (`--aqt-tank`,
 * `--aqt-damage`, `--aqt-support`) that every other role surface uses. Colour is
 * never the only cue: every chip and every stepper still names its slot kind, as
 * `sr-only` text plus a hover title.
 */
const SLOT_CHIP: Record<RosterSlotCode, string> = {
  tank: "border-[color:var(--aqt-tank)]/35 bg-[color:var(--aqt-tank)]/12 text-[color:var(--aqt-tank)]",
  damage: "border-[color:var(--aqt-damage)]/35 bg-[color:var(--aqt-damage)]/12 text-[color:var(--aqt-damage)]",
  support:
    "border-[color:var(--aqt-support)]/35 bg-[color:var(--aqt-support)]/12 text-[color:var(--aqt-support)]",
  flex: "border-border/60 bg-muted/25 text-muted-foreground"
};

/**
 * A slot kind's glyph: the same marks the draft room, the rosters and the
 * registration form already use, so one slot kind reads identically everywhere.
 * Always decorative -- every call site pairs it with the slot name.
 */
function SlotIcon({ code, size = 18 }: Readonly<{ code: RosterSlotCode; size?: number }>) {
  if (isRoleSlotCode(code)) {
    return (
      <PlayerRoleIcon
        role={getRoleIconName(code)}
        size={size}
        color={ROLE_ACCENT[code]}
        decorative
      />
    );
  }
  // Inherits the surrounding text colour; `flex` has no hue of its own.
  return <FlexIcon width={size} height={size} />;
}

interface RosterShapeEditorProps {
  /** Stored override, straight off `Tournament.roster_slots_json` or a pickup
   * mix's `config_json.role_mask` -- whichever entity `entity` names. */
  value: RosterSlotMap | null;
  /**
   * Server-resolved shape (`Tournament.roster_shape` / `CustomGame.roster_shape`).
   * Every derived number -- team size, draft rounds, whether any slot asks for a
   * role -- is read from here; `null` only when the read did not opt into it.
   */
  effective: RosterShape | null;
  /**
   * `true` while a draft session is in flight. The write-path guard would reject
   * a change, so the form says so up front instead of letting the save 400.
   */
  locked?: boolean;
  disabled?: boolean;
  /** Emits the value for `TournamentUpdate.roster_slots_json` (or a mix's
   * `role_mask`); `null` = inherit. */
  onChange: (next: RosterSlotMap | null) => void;
  className?: string;
  /**
   * Which entity owns the override, for the two sentences that name it by word
   * rather than by shape ("this {entity} pins its own shape..."). Both entities
   * inherit the same workspace default, so every other string stays as-is.
   */
  entity?: "tournament" | "mix" | "account";
}

export function RosterShapeEditor({
  value,
  effective,
  locked = false,
  disabled = false,
  onChange,
  className,
  entity = "tournament"
}: Readonly<RosterShapeEditorProps>) {
  const t = useTranslations("rosterShape");
  const errorId = useId();
  const inherited = effective?.slots ?? {};
  const [selection, setSelection] = useState<RosterShapeSelection>(() =>
    initialSelection(value, inherited)
  );
  // `value` is the payload, which cannot express the editor's whole state: it
  // drops the counts kept under `inherit` and the mode behind an override that
  // equals a preset. So it is re-seeded only when the prop actually diverges
  // from what this editor last emitted -- a parent reset or a background
  // refetch -- and never on the editor's own round trip through the parent.
  //
  // Adjusted during render rather than in an effect: React re-runs the component
  // with the new state before committing, so the stale selection is never
  // painted. An effect would paint it first, then correct it -- and would trip
  // react-hooks/set-state-in-effect for exactly that reason.
  const [lastEmitted, setLastEmitted] = useState(() => JSON.stringify(value));
  const incoming = JSON.stringify(value);
  if (incoming !== lastEmitted) {
    setLastEmitted(incoming);
    setSelection(initialSelection(value, inherited));
  }

  const apply = (next: RosterShapeSelection) => {
    setSelection(next);
    const payload = slotsPayload(next);
    setLastEmitted(JSON.stringify(payload));
    onChange(payload);
  };

  const error = payloadTotalError(slotsPayload(selection));
  const readOnly = locked || disabled;
  const isInherit = selection.mode === "inherit";
  // In inherit mode the resolved shape IS the outcome, so the totals line reads
  // the server numbers; an override shows the live edit.
  const shownTotal = isInherit && effective ? effective.team_size : slotsTotal(selection.slots);
  const shownRounds = effective
    ? draftRoundsPreview(shownTotal, effective)
    : Math.max(shownTotal - 1, 0);
  const previewSlots = previewSlotRows(isInherit ? inherited : selection.slots);

  // Where the shape comes from, keyed off the mode being EDITED rather than the
  // saved resolution: while an override is in the form, saying "inherited from
  // the workspace" describes a state the admin is in the middle of leaving.
  const sourceNote = (() => {
    if (!effective) return null;
    // An account-scoped shape has no single workspace behind it: it applies to
    // every mix its owner hosts, each in whatever workspace it runs in, so
    // neither "inherited from THE workspace" nor a saved-source note fits.
    if (entity === "account") return t(isInherit ? "willInheritAccount" : "overridingAccount");
    if (!isInherit) return t(entity === "mix" ? "overridingMix" : "overriding");
    if (effective.source === "tournament") {
      return t(entity === "mix" ? "willInheritMix" : "willInherit");
    }
    return t("inherited", {
      source: t(
        effective.source === "workspace"
          ? "inheritedSources.workspace"
          : "inheritedSources.default"
      ),
      shape: orderSlotCodes(effective.slots)
        .map((code) => `${effective.slots[code]} ${t(`slotCodes.${code}`)}`)
        .join(" · ")
    });
  })();

  return (
    <Card className={cn("border-border/40 bg-card/50", className)}>
      <CardHeader className="pb-4">
        <div className="flex items-center gap-2">
          <Users className="size-4 text-primary" aria-hidden />
          <CardTitle asChild className="text-sm font-semibold">
            <h2>{t("title")}</h2>
          </CardTitle>
        </div>
        <CardDescription className="text-xs">{t("description")}</CardDescription>
      </CardHeader>

      {/* Controls first, outcome underneath at full width. Side by side, the
          outcome -- one wrapped strip of slot chips -- got a 1fr column it left
          half empty, while the four steppers were crammed into 78px cells in a
          20rem one. */}
      <CardContent className="space-y-5">
        {locked && (
          <p
            className={cn(
              "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
              TONE_CLASS.warning
            )}
          >
            <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {t("locked")}
          </p>
        )}

        <div className="grid items-start gap-x-6 gap-y-5 sm:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <div>
            <Label htmlFor="settings-roster-shape-mode" className="text-xs">
              {t("mode")}
            </Label>
            <Select
              value={selection.mode}
              disabled={readOnly}
              onValueChange={(next) =>
                apply(selectMode(selection, next as RosterShapeSelection["mode"]))
              }
            >
              <SelectTrigger id="settings-roster-shape-mode" className="mt-1.5 bg-background/50">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROSTER_SHAPE_MODES.map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {t(`modes.${mode}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {sourceNote && <p className="mt-2 text-xs text-muted-foreground">{sourceNote}</p>}
          </div>

          {!isInherit && (
            <div>
              <span className={EYEBROW_CLASS}>{t("slots")}</span>
              {/* Counters labelled by the slot glyph rather than the word: the
                  dot-plus-name pair spent most of each cell restating what the
                  colour already said, and the glyph is what the draft room and
                  the roster views show. Cells size to content and wrap, so the
                  row no longer has to fit a fixed four-up grid. */}
              <div className="mt-2 flex flex-wrap gap-2">
                {ROSTER_SLOT_CODES.map((code) => {
                  const label = t(`slotCodes.${code}`);
                  return (
                    <div
                      key={code}
                      className="flex items-center gap-2 rounded-xl border border-border/50 bg-muted/20 p-1.5"
                    >
                      <Label
                        htmlFor={`settings-roster-slot-${code}`}
                        title={label}
                        className="flex size-8 shrink-0 items-center justify-center text-muted-foreground"
                      >
                        <SlotIcon code={code} />
                        <span className="sr-only">{label}</span>
                      </Label>
                      <NumberInput
                        id={`settings-roster-slot-${code}`}
                        integer
                        min={0}
                        max={MAX_SLOT_COUNT}
                        disabled={readOnly}
                        aria-invalid={error !== null}
                        aria-describedby={error ? errorId : undefined}
                        value={selection.slots[code] ?? 0}
                        onValueChange={(next) => apply(setSlotCount(selection, code, next ?? 0))}
                        className="h-8 w-14 bg-background/50 px-2 text-center tabular-nums"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {error && (
          <p
            id={errorId}
            className={cn("rounded-lg border px-3 py-2 text-xs", TONE_CLASS.danger)}
            role="alert"
          >
            {t(`errors.${error}`)}
          </p>
        )}

        {/* The answer to "what did I just configure" without starting a draft:
            the slot list a captain will be handed, as one strip that now has the
            whole card to wrap across. */}
        <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={EYEBROW_CLASS}>{t("preview")}</span>
            <p className="text-sm font-semibold tabular-nums text-foreground">
              {t("total", { total: shownTotal, rounds: shownRounds })}
            </p>
          </div>
          {previewSlots.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">{t("previewEmpty")}</p>
          ) : (
            <ol className="mt-3 flex flex-wrap gap-1.5">
              {previewSlots.map((code, index) => (
                <li
                  key={`${code}-${index}`}
                  title={t(`slotCodes.${code}`)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                    SLOT_CHIP[code]
                  )}
                >
                  <span className="tabular-nums opacity-60">{index + 1}</span>
                  <SlotIcon code={code} size={14} />
                  <span className="sr-only">{t(`slotCodes.${code}`)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
