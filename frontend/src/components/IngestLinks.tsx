"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { IngestClient } from "@/types/discipline.types";

const LINK_CLASS = "font-medium text-[color:var(--aqt-teal)] underline underline-offset-2";

/** Where a player gets the game's match uploader (its descriptor's `ingest_client`): instructions first, then the installer. */
export function IngestLinks({ client, className }: Readonly<{ client: IngestClient; className?: string }>) {
  const t = useTranslations("mixes.ingest");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <a href={client.instructions_url} target="_blank" rel="noreferrer" className={LINK_CLASS}>
        {t("instructionsLink")}
      </a>
      <a href={client.installer_url} target="_blank" rel="noreferrer" className={LINK_CLASS}>
        {t("installerLink")}
      </a>
    </span>
  );
}
