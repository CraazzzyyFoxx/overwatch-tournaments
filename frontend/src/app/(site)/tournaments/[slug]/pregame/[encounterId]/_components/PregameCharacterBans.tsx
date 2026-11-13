"use client";

import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadPregameUI } from "@/disciplines/registry/pregame";
import type { SlotProps } from "@/disciplines/types";

import type { RoomMetadata } from "./usePregameRoomData";

/**
 * The room's character bans, rendered by its game's `pregameCharacterBans` module slot. The slot needs the
 * game's native metadata, so its three states stay distinct: loading shows a placeholder, a failed read says
 * the list could not be shown and offers a retry (the committed bans are still there, only their display
 * settings are missing), and a game whose module has no renderer shows nothing.
 */
export function PregameCharacterBans({
  metadata,
  ...slotProps
}: Readonly<{ metadata: RoomMetadata } & Omit<SlotProps["pregameCharacterBans"], "metadata">>) {
  const t = useTranslations("pickBan.room");

  if (metadata.status === "pending") {
    return <Skeleton aria-hidden className="h-16 w-full" />;
  }
  if (metadata.status === "error") {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-[color:var(--aqt-rose)]/40 p-2.5 text-xs"
      >
        <span className="min-w-0 flex-1">{t("heroBans.metadataError")}</span>
        <Button size="sm" variant="outline" onClick={metadata.retry}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  return (
    <DisciplineWidget
      discipline={metadata.metadata.discipline.code}
      load={loadPregameUI}
      slot="pregameCharacterBans"
      capabilities={metadata.metadata.discipline.capabilities}
      props={{ ...slotProps, metadata: metadata.metadata }}
      fallback={null}
    />
  );
}
