"use client";

import type { ReactNode } from "react";
import { Gamepad2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useScopePillOpen } from "@/components/workspace/scope-pill-store";
import { cn } from "@/lib/utils";

/**
 * Stands in for the game-bound filters under "all games" (spec §6.2); opens the scope pill. `children` replaces the
 * generic wording (a one-game page naming the game it shows).
 */
export function GameFilterHint({ className, children }: Readonly<{ className?: string; children?: ReactNode }>) {
  const t = useTranslations("common.discipline");
  const setOpen = useScopePillOpen((state) => state.setOpen);

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => setOpen(true)}
      className={cn(
        "max-w-full gap-1.5 rounded-full border-dashed bg-transparent text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-2)] [&_svg]:size-3.5",
        className
      )}
    >
      <Gamepad2 aria-hidden />
      <span className="truncate">{children ?? t("filterHint")}</span>
    </Button>
  );
}
