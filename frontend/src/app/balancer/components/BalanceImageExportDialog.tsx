"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { capturePngBlob, copyImageBlob, waitForImages, waitForLayout } from "@/lib/image-capture";
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

function chunkBalanceTeams(teams: InternalBalanceTeam[]): TeamChunk[] {
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
}: Readonly<BalanceImageExportDialogProps>) {
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
                      <div className="text-xs font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
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

[Showing lines 1-300 of 514. Use :301 to continue]