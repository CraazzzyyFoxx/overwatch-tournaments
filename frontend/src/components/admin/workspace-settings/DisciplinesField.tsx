"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { GameMark } from "@/components/workspace/GameMark";
import { useDisciplines } from "@/hooks/useDisciplineMetadata";
import { resolveOwnerGrid } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Workspace } from "@/types/workspace.types";

const MARK_SIZE = 28;

/**
 * One game between hairlines: the list sits in a settings card, and a bordered
 * tile per game was a card inside a card (DESIGN §5). Grip, position and mark
 * sit in fixed columns so names line up across enabled and switched-off rows.
 */
const ROW_CLASS =
  "flex min-h-14 items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[color:var(--aqt-overlay-2)]";
/** The grip's own box, without the bordered tile it wears in denser tables. */
const GRIP_CLASS = "border-transparent bg-transparent hover:bg-[color:var(--aqt-overlay-3)]";

/**
 * The workspace's games: the enabled ones in priority order, then the rest.
 *
 * Order is data, not cosmetics — `disciplines_enabled[0]` is the game a
 * tournament, grid or mix gets when none is named (`workspace_discipline`,
 * `useDivisionGrid`), and the server stores the list exactly as sent. So the
 * enabled rows are a drag list with their position printed, and nothing
 * re-sorts them; turning a game on appends it, turning it off removes it and
 * the next one becomes default.
 *
 * What each row cannot say with its switch it says in words under the name:
 * which game is the default, why the last one cannot be turned off (state
 * disables with a visible reason, DESIGN §14), and that a game with neither a
 * built-in ladder nor a division grid cannot host a tournament yet. A game with
 * a ladder never warns: saving provisions its own grid, and until then its
 * ranks resolve through the ladder.
 */
export function DisciplinesField({
  workspace,
  value,
  onChange
}: Readonly<{
  workspace: Pick<Workspace, "id" | "effective_division_grid_versions">;
  /** Enabled codes, in priority order — the form's `disciplines_enabled`. */
  value: readonly string[];
  onChange: (next: string[]) => void;
}>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.general.disciplines");
  const { data: installed = [] } = useDisciplines(workspace.id);
  // Only installed games get a row: the server has already refused anything else.
  const enabled = value.flatMap((code) => installed.filter((item) => item.code === code));
  const available = installed.filter((item) => !value.includes(item.code));

  return (
    <div className="w-full">
      <SortableRows
        items={enabled}
        getId={(item) => item.code}
        onReorder={(next) => onChange(next.map((item) => item.code))}
        className="divide-y divide-border/60"
      >
        {(item, index) => (
          <EnabledRow
            key={item.code}
            item={item}
            position={index + 1}
            // The only way to have zero would be to turn this one off.
            last={enabled.length === 1}
            gridless={!item.capabilities.native_ladder && resolveOwnerGrid(workspace, item.code) === null}
            onDisable={() => onChange(value.filter((code) => code !== item.code))}
          />
        )}
      </SortableRows>

      {available.length > 0 ? (
        <div className="mt-3 border-t border-border/60 pt-3">
          <p className={cn(eyebrowClass("muted"), "px-2 pb-1")}>{t("available")}</p>
          <div className="divide-y divide-border/60">
            {available.map((item) => (
              <div key={item.code} className={ROW_CLASS}>
                {/* Grip and position columns, empty: these rows have no order. */}
                <span className="size-6 shrink-0" aria-hidden="true" />
                <span className="w-4 shrink-0" aria-hidden="true" />
                <GameMark
                  discipline={item}
                  size={MARK_SIZE}
                  decorative
                  className="opacity-50 grayscale"
                />
                <span className="min-w-0 flex-1 truncate text-ui text-[color:var(--aqt-fg-muted)]">
                  {item.name}
                </span>
                <Switch
                  checked={false}
                  onCheckedChange={() => onChange([...value, item.code])}
                  aria-label={t("toggle", { name: item.name })}
                />
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EnabledRow({
  item,
  position,
  last,
  gridless,
  onDisable
}: Readonly<{
  item: DisciplineDescriptor;
  position: number;
  last: boolean;
  gridless: boolean;
  onDisable: () => void;
}>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.general.disciplines");
  const { ref, style, handleProps, isDragging } = useSortableRow(item.code);
  const notes = [position === 1 ? t("defaultHint") : null, last ? t("lastEnabled") : null].filter(
    Boolean
  );

  return (
    <div
      ref={ref}
      style={style}
      className={cn(
        ROW_CLASS,
        isDragging &&
          "bg-[color:var(--aqt-card-2)] ring-1 ring-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-card-2)]"
      )}
    >
      <SortableGrip
        handleProps={handleProps}
        label={t("reorder", { name: item.name })}
        className={GRIP_CLASS}
      />
      {/* The position is the priority; the DOM order already says it to assistive tech. */}
      <span
        aria-hidden="true"
        className="aqt-tnum w-4 shrink-0 text-center text-label text-[color:var(--aqt-fg-faint)]"
      >
        {position}
      </span>
      <GameMark discipline={item} size={MARK_SIZE} decorative />
      <div className="min-w-0 flex-1">
        <p className="truncate text-ui font-medium text-foreground">{item.name}</p>
        {notes.length > 0 ? (
          // Wraps rather than truncates: the last game's reason for a locked
          // switch is the part a cut-off line would hide.
          <p className="mt-0.5 text-caption text-pretty text-muted-foreground">{notes.join(" · ")}</p>
        ) : null}
        {gridless ? (
          <p className="mt-0.5 flex items-start gap-1.5 text-caption text-warning">
            <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            <span className="min-w-0">{t("noGrid")}</span>
          </p>
        ) : null}
      </div>
      <Switch
        checked
        disabled={last}
        onCheckedChange={onDisable}
        aria-label={t("toggle", { name: item.name })}
      />
    </div>
  );
}
