"use client";

import React from "react";
import { ChevronDown, Wrench } from "lucide-react";

import { Card } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import MLAdminToolbar from "@/app/(site)/tournaments/analytics/components/MLAdminToolbar";

interface OrganizerToolsProps {
  tournamentId: number;
  workspaceId?: number | null;
}

/**
 * Groups every organizer-only action (recalculate, train, manual edits) behind
 * one collapsed "Organizer tools" panel, so the default read view is free of
 * admin controls. Only rendered for users with `analytics.update`.
 */
export default function OrganizerTools({ tournamentId, workspaceId }: OrganizerToolsProps) {
  const [open, setOpen] = React.useState(false);

  return (
    <Card className="overflow-hidden border-border/60">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-5 py-3 text-left hover:bg-white/[0.02] transition-colors">
          <Wrench className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <span className="font-display text-[15px] font-bold uppercase tracking-[0.04em] text-foreground">
            Organizer tools
          </span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            recalculate · train · manual edits
          </span>
          <ChevronDown
            className={cn(
              "ml-auto h-4 w-4 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-border/60 px-5 py-4">
          <MLAdminToolbar tournamentId={tournamentId} workspaceId={workspaceId ?? null} />
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
