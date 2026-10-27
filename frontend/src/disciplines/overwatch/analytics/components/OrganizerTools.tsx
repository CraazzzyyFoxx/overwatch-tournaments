"use client";

import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import MLAdminToolbar from "@/disciplines/overwatch/analytics/components/MLAdminToolbar";

interface OrganizerToolsProps {
  tournamentId: number;
  workspaceId?: number | null;
}

/**
 * Groups the organizer-only analytics jobs (recalculate, train) behind one
 * collapsed "Organizer tools" panel, so the default read view is free of
 * admin controls. Only rendered for users with `analytics.update`.
 */
export default function OrganizerTools({ tournamentId, workspaceId }: Readonly<OrganizerToolsProps>) {
  const t = useTranslations();

  return (
    <Card className="p-2">
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="group/trigger w-full justify-between">
            {t("analytics.organizer.title")}
            <ChevronDown aria-hidden className={triggerChevronClass} />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 border-t border-[color:var(--aqt-border)] px-4 pb-2 pt-4">
          <MLAdminToolbar tournamentId={tournamentId} workspaceId={workspaceId ?? null} />
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
