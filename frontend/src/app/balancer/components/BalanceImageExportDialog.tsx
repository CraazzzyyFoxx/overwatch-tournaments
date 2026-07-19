"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toBlob } from "html-to-image";
import { AlertCircle, Copy, Download, Images, Loader2 } from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { resolveDivisionFromRank, getDivisionIconSrc, getDivisionLabel } from "@/lib/division-grid";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { formatSubRoleLabel } from "@/utils/player";
import type { InternalBalancePayload, InternalBalanceTeam } from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import {
  BALANCE_ROSTER_KEYS,
  TEAM_BADGE_ACCENTS,
  calculateTeamAverageFromPayload,
  calculateTeamTotalFromPayload
} from "./balancer-page-helpers";

const TEAMS_PER_IMAGE = 10;
const EXPORT_WIDTH = 1920;
const EXPORT_BACKGROUND = "#090a10";

type BalanceImageExportDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  payload: InternalBalancePayload | null;
  divisionGrid: DivisionGrid;
  tournamentId: number | null;
};

type TeamChunk = {
  id: string;
  entries: TeamExportEntry[];
};

type GeneratedImage = {
  id: string;
  label: string;
  blob: Blob;
  url: string;
};

type TeamExportEntry = {
  team: InternalBalanceTeam;
  teamIndex: number;
};

export function chunkBalanceTeams(teams: InternalBalanceTeam[]): TeamChunk[] {
  const chunks: TeamChunk[] = [];

  for (let index = 0; index < teams.length; index += TEAMS_PER_IMAGE) {
    chunks.push({
      id: `part-${chunks.length + 1}`,
      entries: teams.slice(index, index + TEAMS_PER_IMAGE).map((team, offset) => ({
        team,
        teamIndex: index + offset
      }))
    });
  }

  return chunks;
}

export function BalanceImageExportDialog({
  open,
  onOpenChange,
  payload,
  divisionGrid,
  tournamentId
}: BalanceImageExportDialogProps) {
  const chunkRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const fullImageRef = useRef<HTMLDivElement | null>(null);
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [fullImageBlob, setFullImageBlob] = useState<Blob | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chunks = useMemo(() => chunkBalanceTeams(payload?.teams ?? []), [payload]);

  const clearGeneratedImages = useCallback(() => {
    setImages((current) => {
      current.forEach((image) => URL.revokeObjectURL(image.url));
      return [];
    });
    setFullImageBlob(null);
  }, []);

  useEffect(() => () => clearGeneratedImages(), [clearGeneratedImages]);

  useEffect(() => {
    if (!open) {
      clearGeneratedImages();
      setError(null);
      setIsGenerating(false);
      return;
    }

    if (!payload || chunks.length === 0) {
      return;
    }

    let cancelled = false;

    const generateImages = async () => {
      const objectUrls: string[] = [];

      setIsGenerating(true);
      setError(null);
      clearGeneratedImages();

      try {
        await waitForLayout();

        const nextImages: GeneratedImage[] = [];

        for (const [index, chunk] of chunks.entries()) {
          const node = chunkRefs.current[chunk.id];
          if (!node) {
            throw new Error("Image export node is unavailable");
          }

          await waitForImages(node);
          const blob = await capturePngBlob(node);
          const url = URL.createObjectURL(blob);
          objectUrls.push(url);

          nextImages.push({
            id: chunk.id,
            label: `Image ${index + 1}`,
            blob,
            url
          });
        }

        if (!fullImageRef.current) {
          throw new Error("Full image export node is unavailable");
        }

        await waitForImages(fullImageRef.current);
        const nextFullImageBlob = await capturePngBlob(fullImageRef.current);

        if (cancelled) {
          objectUrls.forEach((url) => URL.revokeObjectURL(url));
          return;
        }

        setImages(nextImages);
        setFullImageBlob(nextFullImageBlob);
      } catch {
        objectUrls.forEach((url) => URL.revokeObjectURL(url));

        if (!cancelled) {
          setError("Could not generate balance images.");
          notify.error("Image export failed");
        }
      } finally {
        if (!cancelled) {
          setIsGenerating(false);
        }
      }
    };

    void generateImages();

    return () => {
      cancelled = true;
    };
  }, [chunks, clearGeneratedImages, open, payload]);

  const handleCopyImage = useCallback(async (blob: Blob, title: string) => {
    try {
      await copyImageBlob(blob);
      notify.success(title);
    } catch {
      notify.error("Clipboard image copy unavailable");
    }
  }, []);

  const handleDownloadAll = useCallback(() => {
    images.forEach((image, index) => {
      const anchor = document.createElement("a");
      anchor.href = image.url;
      anchor.download = `balance-${tournamentId ?? "export"}-part-${index + 1}.png`;
      anchor.click();
    });
  }, [images, tournamentId]);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex h-[min(860px,calc(100vh-2rem))] w-[min(1180px,calc(100vw-2rem))] max-w-none flex-col gap-0 overflow-hidden border-border bg-popover p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/60">
          <DialogHeader className="shrink-0 border-b border-[color:var(--aqt-border)] px-5 py-4 text-left">
            <div className="flex flex-col gap-3 pr-8 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <DialogTitle className="flex items-center gap-2 text-base font-semibold text-[color:var(--aqt-fg)]">
                  <Images className="h-4 w-4 text-cyan-200" />
                  Balance Images
                </DialogTitle>
                <DialogDescription className="mt-1 text-xs text-[color:var(--aqt-fg-dim)]">
                  Preview, copy, or download readable team images.
                </DialogDescription>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl border-[color:var(--aqt-border-2)] bg-white/[0.04] text-[color:var(--aqt-fg-muted)] hover:bg-white/[0.08] hover:text-[color:var(--aqt-fg)]"
                  onClick={handleDownloadAll}
                  disabled={isGenerating || images.length === 0}
                >
                  <Download className="h-4 w-4" />
                  Download all
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl border-[color:var(--aqt-border-2)] bg-white/[0.04] text-[color:var(--aqt-fg-muted)] hover:bg-white/[0.08] hover:text-[color:var(--aqt-fg)]"
                  onClick={() => {
                    if (fullImageBlob) {
                      void handleCopyImage(fullImageBlob, "Full image copied");
                    }
                  }}
                  disabled={isGenerating || !fullImageBlob}
                >
                  <Copy className="h-4 w-4" />
                  Copy full image
                </Button>
              </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {isGenerating ? (
              <div className="flex min-h-64 items-center justify-center rounded-2xl border border-[color:var(--aqt-border)] bg-white/[0.03] text-sm text-[color:var(--aqt-fg-muted)]">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Generating images...
              </div>
            ) : null}

            {!isGenerating && error ? (
              <div className="flex min-h-64 items-center justify-center rounded-2xl border border-rose-300/15 bg-rose-500/8 px-4 text-sm text-rose-100">
                <AlertCircle className="mr-2 h-4 w-4" />
                {error}
              </div>
            ) : null}

            {!isGenerating && !error ? (
              <div className="flex flex-col gap-4">
                {images.map((image, index) => (
                  <div
                    key={image.id}
                    className="overflow-hidden rounded-xl border border-border bg-card"
                  >
                    <div className="flex items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--aqt-fg-muted)]">
                        {image.label}
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="rounded-xl border-[color:var(--aqt-border-2)] bg-white/[0.04] text-[color:var(--aqt-fg-muted)] hover:bg-white/[0.08] hover:text-[color:var(--aqt-fg)]"
                        onClick={() =>
                          void handleCopyImage(image.blob, `Image ${index + 1} copied`)
                        }
                      >
                        <Copy className="h-4 w-4" />
                        Copy
                      </Button>
                    </div>
                    <div className="bg-background p-2">
                      <Image
                        src={image.url}
                        alt={`${image.label} preview`}
                        width={EXPORT_WIDTH}
                        height={720}
                        unoptimized
                        className="h-auto w-full rounded-xl border border-[color:var(--aqt-border)]"
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {open && payload ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed top-0 -z-10"
          style={{ left: "-100000px" }}
        >
          {chunks.map((chunk) => (
            <BalanceImageCaptureFrame
              key={chunk.id}
              refCallback={(node) => {
                chunkRefs.current[chunk.id] = node;
              }}
              entries={chunk.entries}
              divisionGrid={divisionGrid}
            />
          ))}
          <BalanceImageCaptureFrame
            refCallback={(node) => {
              fullImageRef.current = node;
            }}
            entries={payload.teams.map((team, teamIndex) => ({ team, teamIndex }))}
            divisionGrid={divisionGrid}
          />
        </div>
      ) : null}
    </>
  );
}

function BalanceImageCaptureFrame({
  refCallback,
  entries,
  divisionGrid
}: {
  refCallback: (node: HTMLDivElement | null) => void;
  entries: TeamExportEntry[];
  divisionGrid: DivisionGrid;
}) {
  return (
    <div
      ref={refCallback}
      className="mb-6 bg-[#090a10] p-4 text-[color:var(--aqt-fg)]"
      style={{ width: EXPORT_WIDTH }}
    >
      <div className="grid grid-cols-5 gap-3">
        {entries.map(({ team, teamIndex }) => (
          <BalanceExportTeamCard
            key={`${team.id}-${teamIndex}`}
            team={team}
            teamIndex={teamIndex}
            divisionGrid={divisionGrid}
          />
        ))}
      </div>
    </div>
  );
}

function BalanceExportTeamCard({
  team,
  teamIndex,
  divisionGrid
}: {
  team: InternalBalanceTeam;
  teamIndex: number;
  divisionGrid: DivisionGrid;
}) {
  const total = Math.round(calculateTeamTotalFromPayload(team));
  const average = Math.round(calculateTeamAverageFromPayload(team));
  const teamAccent = TEAM_BADGE_ACCENTS[teamIndex % TEAM_BADGE_ACCENTS.length];

  return (
    <div className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[#101116] shadow-[0_16px_48px_rgba(0,0,0,0.24)]">
      <div className="flex items-start justify-between gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div
            className={cn(
              "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
              teamAccent
            )}
          >
            #{team.id}
          </div>
          <div className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]" title={team.name}>
            {team.name}
          </div>
        </div>

        <div className="shrink-0 text-right">
          <div className="flex flex-wrap justify-end gap-x-3 gap-y-1 text-[11px] font-medium text-[color:var(--aqt-fg-muted)]">
            <span>
              Total: <span className="tabular-nums text-[color:var(--aqt-fg)]">{total}</span>
            </span>
            <span>
              Avg: <span className="tabular-nums text-[color:var(--aqt-fg)]">{average}</span>
            </span>
          </div>
        </div>
      </div>

      <table className="w-full min-w-90 caption-bottom text-sm">
        <thead>
          <tr className="border-b border-[color:var(--aqt-border)]">
            <th className="h-8 w-13 px-4 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Role
            </th>
            <th className="h-8 min-w-45 px-0 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Player
            </th>
            <th className="h-8 w-18 px-2 text-center align-middle text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Rank
            </th>
            <th className="h-8 w-22 px-3 text-center align-middle text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Prefs
            </th>
          </tr>
        </thead>
        {BALANCE_ROSTER_KEYS.map((roleKey) => (
          <tbody key={`${team.id}-${roleKey}`}>
            {team.roster[roleKey].map((player) => (
              <tr key={player.uuid} className="border-b border-[color:var(--aqt-border)]">
                <td className="w-13 px-4 py-2.5">
                  <div className="flex justify-center">
                    <PlayerRoleIcon role={roleKey} size={18} />
                  </div>
                </td>
                <td className="min-w-45 py-2.5 pr-2">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]"
                        title={player.name}
                      >
                        {player.name}
                      </span>
                    </div>
                    {formatSubRoleLabel(player.sub_role) ? (
                      <span className="truncate text-[10px] font-medium uppercase tracking-[0.12em] text-[color:var(--aqt-fg-dim)]">
                        {formatSubRoleLabel(player.sub_role)}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="w-18 px-2 py-2.5">
                  <ExportDivisionIcon divisionGrid={divisionGrid} rank={player.assigned_rating} />
                </td>
                <td className="w-22 px-3 py-2.5">
                  <div className="flex items-center justify-center gap-1">
                    {player.role_preferences.length > 0 ? (
                      player.role_preferences.slice(0, 3).map((preference, index) => (
                        <span
                          key={`${player.uuid}-${preference}-${index}`}
                          className="flex items-center justify-center opacity-85"
                        >
                          <PlayerRoleIcon role={preference} size={14} />
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-[color:var(--aqt-fg-faint)]">-</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}

            {team.roster[roleKey].length === 0 ? (
              <tr className="border-b border-[color:var(--aqt-border)]">
                <td
                  colSpan={4}
                  className="px-3 py-2.5 text-center text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]"
                >
                  Empty {roleKey.toLowerCase()}
                </td>
              </tr>
            ) : null}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function ExportDivisionIcon({ divisionGrid, rank }: { divisionGrid: DivisionGrid; rank: number }) {
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const src = getDivisionIconSrc(divisionGrid, division);
  const label = getDivisionLabel(divisionGrid, division);

  if (!src || division == null) {
    return <div className="text-center text-xs text-[color:var(--aqt-fg-faint)]">-</div>;
  }

  return (
    <div className="flex justify-center">
      <Image
        src={src}
        alt={label ?? `Division ${division}`}
        width={26}
        height={26}
        loading="eager"
        unoptimized
      />
    </div>
  );
}

async function capturePngBlob(node: HTMLDivElement): Promise<Blob> {
  const blob = await toBlob(node, {
    cacheBust: true,
    backgroundColor: EXPORT_BACKGROUND,
    pixelRatio: 2
  });

  if (!blob) {
    throw new Error("Could not create PNG blob");
  }

  return blob;
}

async function copyImageBlob(blob: Blob): Promise<void> {
  if (
    !navigator.clipboard ||
    typeof navigator.clipboard.write !== "function" ||
    typeof ClipboardItem === "undefined"
  ) {
    throw new Error("Clipboard image copy is not supported");
  }

  await navigator.clipboard.write([
    new ClipboardItem({
      "image/png": blob
    })
  ]);
}

async function waitForLayout(): Promise<void> {
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

async function waitForImages(node: HTMLElement): Promise<void> {
  const imageElements = Array.from(node.querySelectorAll("img"));

  await Promise.all(
    imageElements.map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }

          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        })
    )
  );
}
