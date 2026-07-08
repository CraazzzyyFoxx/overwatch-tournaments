"use client";

import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

export interface SpecializationOption {
  value: string;
  label: string;
}

export function SpecializationBlock({
  label,
  value,
  options,
  onChange,
  disabled = false,
  onDisabledSelect,
  hideLabel = false,
}: {
  label: string;
  value: string;
  options: SpecializationOption[];
  onChange: (nextValue: string) => void;
  disabled?: boolean;
  onDisabledSelect?: (nextValue: string) => void;
  hideLabel?: boolean;
}) {
  const t = useTranslations();
  const handleSelect = (nextValue: string) => {
    if (disabled) {
      onDisabledSelect?.(nextValue);
      return;
    }

    onChange(nextValue);
  };

  return (
    <div className="space-y-1.5">
      {!hideLabel && (
        <p
          className={cn(
            "text-[11px] font-medium uppercase tracking-[0.12em]",
            disabled ? "text-white/28" : "text-white/42",
          )}
        >
          {label}
        </p>
      )}
      <div className="flex flex-nowrap gap-1 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <SubrolePill
          label={t("registration.roles.any")}
          active={value === ""}
          muted={disabled}
          disabled={disabled && !onDisabledSelect}
          onClick={() => handleSelect("")}
        />

        {options.map((option) => (
          <SubrolePill
            key={option.value}
            label={option.label}
            active={value === option.value}
            muted={disabled}
            disabled={disabled && !onDisabledSelect}
            onClick={() => handleSelect(option.value)}
          />
        ))}
      </div>
    </div>
  );
}

function SubrolePill({
  label,
  active,
  muted = false,
  disabled = false,
  onClick,
}: {
  label: string;
  active: boolean;
  muted?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      aria-disabled={disabled || muted}
      className={cn(
        "shrink-0 whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium leading-4 transition-colors",
        disabled && "cursor-default opacity-45",
        muted && !disabled && "opacity-45",
        !disabled && active
          ? "border-blue-400/60 bg-blue-500/18 text-blue-100"
          : "border-white/10 bg-white/[0.03] text-white/55",
        !disabled && !active && "hover:bg-white/[0.06] hover:text-white/75",
      )}
    >
      {label}
    </button>
  );
}
