"use client";

import { type ReactNode } from "react";
import { Check } from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ROLE_ACCENTS, getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";

interface SelectionCardProps {
  roleCode: string;
  label: string;
  selected: boolean;
  disabled?: boolean;
  detailsSelectsCard?: boolean;
  reserveHintSpace?: boolean;
  reserveDetailsSpace?: boolean;
  type: "radio" | "checkbox";
  onClick: () => void;
  children?: ReactNode;
  hint?: string;
  compact?: boolean;
  icon?: ReactNode;
}

export function SelectionCard({
  roleCode,
  label,
  selected,
  disabled = false,
  detailsSelectsCard = false,
  reserveHintSpace = false,
  reserveDetailsSpace = false,
  type,
  onClick,
  children,
  hint,
  compact = false,
  icon,
}: SelectionCardProps) {
  const visuals = ROLE_ACCENTS[roleCode];
  const hasDetails = Boolean(children);
  const shouldRenderDetailsSlot = hasDetails || reserveDetailsSpace;
  const detailsAreaInteractive = hasDetails ? detailsSelectsCard : reserveDetailsSpace;

  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border bg-white/[0.02] transition-all",
        selected
          ? visuals.selectedCard
          : disabled
            ? "border-[color:var(--aqt-border-2)] bg-white/[0.015] opacity-55"
            : "border-[color:var(--aqt-border-2)] hover:border-[color:var(--aqt-border-2)] hover:bg-white/[0.04]",
      )}
    >
      <button
        type="button"
        disabled={disabled}
        aria-disabled={disabled}
        onClick={onClick}
        className={cn(
          "flex w-full justify-between gap-3",
          hasDetails || reserveDetailsSpace ? "items-center" : "items-start",
          compact ? "px-2.5 py-[7px]" : "px-2.5 py-2",
          disabled && "cursor-default",
        )}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <RoleIconTile
            roleCode={roleCode}
            compact={compact}
            icon={icon ?? <PlayerRoleIcon role={getRoleIconName(roleCode)} size={18} />}
          />
          <div className="min-w-0 text-left">
            <p className={cn("text-[12px] font-semibold", disabled ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]")}>
              {label}
            </p>
            {hint && (
              <p className={cn("text-xs leading-5", disabled ? "text-[color:var(--aqt-fg-dim)]" : "text-[color:var(--aqt-fg-dim)]")}>
                {hint}
              </p>
            )}
            {!hint && reserveHintSpace && <div aria-hidden="true" className="h-5" />}
          </div>
        </div>

        {type === "radio" ? (
          <SelectionIndicator
            selected={selected}
            selectedBorderClass={visuals.indicator}
            idleBorderClass={visuals.mutedIndicator}
          />
        ) : (
          <CheckboxIndicator
            selected={selected}
            selectedBorderClass={visuals.indicator}
            idleBorderClass={visuals.mutedIndicator}
          />
        )}
      </button>

      {shouldRenderDetailsSlot && (
        <div
          className={cn(
            "border-t border-[color:var(--aqt-border-2)] px-2.5 pb-2.5 pt-1.5",
            detailsAreaInteractive && "cursor-pointer",
          )}
          onClick={detailsAreaInteractive ? onClick : undefined}
          onKeyDown={
            detailsAreaInteractive
              ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onClick();
                  }
                }
              : undefined
          }
          role={detailsAreaInteractive ? "button" : undefined}
          tabIndex={detailsAreaInteractive ? 0 : undefined}
        >
          {hasDetails ? children : <div aria-hidden="true" className="min-h-[42px]" />}
        </div>
      )}
    </div>
  );
}

function RoleIconTile({
  roleCode,
  icon,
  compact = false,
}: {
  roleCode: string;
  icon: ReactNode;
  compact?: boolean;
}) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-xl",
        compact ? "size-7" : "size-8",
        ROLE_ACCENTS[roleCode]?.tile,
      )}
    >
      {icon}
    </span>
  );
}

function SelectionIndicator({
  selected,
  selectedBorderClass,
  idleBorderClass,
}: {
  selected: boolean;
  selectedBorderClass: string;
  idleBorderClass: string;
}) {
  return (
    <span
      className={cn(
        "flex size-4 shrink-0 self-center items-center justify-center rounded-full border transition-colors",
        selected ? selectedBorderClass : idleBorderClass,
      )}
    >
      {selected && <span className="size-1 rounded-full bg-current" />}
    </span>
  );
}

function CheckboxIndicator({
  selected,
  selectedBorderClass,
  idleBorderClass,
}: {
  selected: boolean;
  selectedBorderClass: string;
  idleBorderClass: string;
}) {
  return (
    <span
      className={cn(
        "flex size-4 shrink-0 self-center items-center justify-center rounded-[5px] border transition-colors",
        selected ? selectedBorderClass : idleBorderClass,
      )}
    >
      {selected && <Check className="size-2.5 text-current" strokeWidth={2.8} />}
    </span>
  );
}
