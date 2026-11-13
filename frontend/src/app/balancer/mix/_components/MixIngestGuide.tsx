"use client";

import { useTranslations } from "next-intl";
import { ChevronDown, TriangleAlert } from "lucide-react";

import { IngestLinks } from "@/components/IngestLinks";
import { Alert } from "@/components/ui/alert";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { triggerChevronClass } from "@craazzzyyfoxx/admin-kit/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { IngestClient } from "@/types/discipline.types";

/**
 * The host's note on how a mix's matches reach the site by themselves: through any player's uploader (`client`), the
 * bot's lobby, or the match id pasted after the game. Collapsed, so it costs a line; `warn` -- nobody seated in the
 * lobby uploads and the lobby has no bot -- puts the consequence above it, always open.
 */
export function MixIngestGuide({ warn, client }: Readonly<{ warn: boolean; client: IngestClient }>) {
  const t = useTranslations("mixes.ingest");
  return (
    <div className="flex flex-col gap-2">
      {warn ? (
        <Alert tone="warning">
          <TriangleAlert aria-hidden />
          <p>{t("hostWarning")}</p>
        </Alert>
      ) : null}
      <Card className="overflow-hidden">
        <Collapsible>
          <CollapsibleTrigger className="group/trigger flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-caption font-semibold text-[color:var(--aqt-fg)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
            {t("guideTitle")}
            <ChevronDown aria-hidden className={triggerChevronClass} />
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-2 px-4 pb-3 text-caption text-[color:var(--aqt-fg-muted)]">
            <p>{t("guideIntro")}</p>
            <ul className="list-disc space-y-0.5 pl-5">
              <li>{t("guideIngest")}</li>
              <li>{t("guideBot")}</li>
              <li>{t("guidePaste")}</li>
            </ul>
            <IngestLinks client={client} />
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </div>
  );
}
