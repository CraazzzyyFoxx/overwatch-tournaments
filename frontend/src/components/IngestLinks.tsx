"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

const INSTRUCTIONS_URL = "https://deadlock-api.com/ingest-cache";
const INSTALLER_URL = "https://github.com/deadlock-api/deadlock-api-ingest/releases/latest/download/deadlock-api-ingest-setup.exe";

const LINK_CLASS = "font-medium text-[color:var(--aqt-teal)] underline underline-offset-2";

/** Where a Deadlock player gets deadlock-api-ingest: the official instructions first, then the Windows installer. */
export function IngestLinks({ className }: Readonly<{ className?: string }>) {
  const t = useTranslations("mixes.ingest");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <a href={INSTRUCTIONS_URL} target="_blank" rel="noreferrer" className={LINK_CLASS}>
        {t("instructionsLink")}
      </a>
      <a href={INSTALLER_URL} target="_blank" rel="noreferrer" className={LINK_CLASS}>
        {t("installerLink")}
      </a>
    </span>
  );
}
