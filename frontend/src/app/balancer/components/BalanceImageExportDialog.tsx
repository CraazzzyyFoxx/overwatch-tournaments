"use client";

import Image from "@/components/ui/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, Copy, Download, Images } from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { resolveDivisionFromRank, getDivisionIconSrc, getDivisionLabel } from "@/lib/divisions/grid";
import {
  capturePngBlob,
  copyImageBlob,
  waitForImages,
  waitForLayout
} from "@/lib/image-capture";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { formatSubRoleLabel } from "@/lib/player";
import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalanceTeam
} from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";

import { MUTED_BUTTON_CLASS } from "@/components/balancer/balancer-page-helpers";
import { balanceBucketKeys } from "@/components/balancer/balance-editor-helpers";
import { BalanceTeamHeader } from "@/components/balancer/BalanceTeamHeader";
import { Spinner } from "@/components/ui/spinner";

const TEAMS_PER_IMAGE = 10;
const EXPORT_WIDTH = 1920;

type BalanceImageExportDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  payload: InternalBalancePayload | null;
  divisionGrid: DivisionGrid;
  /** The tournament owner's role dictionary: role names, glyphs and the order of the buckets. `null` while it loads. */
  ontology: RoleOntology | null;
  tournamentId: number | null;
};

type TeamChunk = {
  id: string;
  entries: TeamExportEntry[];
};

type GeneratedImage = {
  id: string;
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
  ontology,
  tournamentId
}: Readonly<BalanceImageExportDialogProps>) {
  const t = useTranslations("balancerTool.page.imageExport");
  const chunkRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const fullImageRef = useRef<HTMLDivElement | null>(null);
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [fullImageBlob, setFullImageBlob] = useState<Blob | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chunks = useMemo(() => chunkBalanceTeams(payload?.teams ?? []), [payload]);
  const bucketKeys = useMemo(
    () => (payload ? balanceBucketKeys(payload, ontology) : []),
    [payload, ontology]
  );

  const clearGeneratedImages = useCallback(() => {
    setImages((current) => {
      current.forEach((image) => URL.revokeObjectURL(image.url));
      return [];
    });
    setFullImageBlob(null);
  }, []);

  useEffect(() => () => clearGeneratedImages(), [clearGeneratedImages]);

  useEffect(() => {
    if (!open || !payload || chunks.length === 0) {
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

        for (const chunk of chunks) {
          const node = chunkRefs.current[chunk.id];
          if (!node) {
            throw new Error("Image export node is unavailable");
          }

          await waitForImages(node);
          const blob = await capturePngBlob(node);
          const url = URL.createObjectURL(blob);
          objectUrls.push(url);

          nextImages.push({ id: chunk.id, blob, url });
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
          setError(t("failed"));
          notify.error(t("failedToast"));
        }
      } finally {
        if (!cancelled) {
          setIsGenerating(false);
        }
      }
    };

    void generateImages();

    // Closing the dialog (or new teams) ends this run: its images go, their
    // object URLs are freed, and the next open starts clean.
    return () => {
      cancelled = true;
      clearGeneratedImages();
      setError(null);
      setIsGenerating(false);
    };
  }, [chunks, clearGeneratedImages, open, payload, t]);

  const handleCopyImage = useCallback(
    async (blob: Blob, title: string) => {
      try {
        await copyImageBlob(blob);
        notify.success(title);
      } catch {
        notify.error(t("copyUnavailable"));
      }
    },
    [t]
  );

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
        <DialogContent variant="panel" className="h-[min(860px,calc(100vh-2rem))] w-[min(1180px,calc(100vw-2rem))] max-w-none">
          <DialogHeader variant="panel">
            <div className="flex flex-col gap-3 pr-8 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <DialogTitle className="flex items-center gap-2">
                  <Images className="h-4 w-4 text-[color:var(--aqt-teal)]" aria-hidden />
                  {t("title")}
                </DialogTitle>
                <DialogDescription className="mt-1">{t("description")}</DialogDescription>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className={MUTED_BUTTON_CLASS}
                  onClick={handleDownloadAll}
                  disabled={isGenerating || images.length === 0}
                >
                  <Download className="h-4 w-4" />
                  {t("downloadAll")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className={MUTED_BUTTON_CLASS}
                  onClick={() => {
                    if (fullImageBlob) {
                      void handleCopyImage(fullImageBlob, t("fullCopied"));
                    }
                  }}
                  disabled={isGenerating || !fullImageBlob}
                >
                  <Copy className="h-4 w-4" />
                  {t("copyFull")}
                </Button>
              </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {isGenerating ? (
              <div className="flex min-h-64 items-center justify-center rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] text-sm text-[color:var(--aqt-fg-muted)]">
                <Spinner className="mr-2" />
                {t("generating")}
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
                  <Card key={image.id} className="overflow-hidden">
                    <div className="flex items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
                      <Eyebrow as="div" tone="muted">
                        {t("image", { index: index + 1 })}
                      </Eyebrow>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className={MUTED_BUTTON_CLASS}
                        onClick={() =>
                          void handleCopyImage(image.blob, t("imageCopied", { index: index + 1 }))
                        }
                      >
                        <Copy className="h-4 w-4" />
                        {t("copy")}
                      </Button>
                    </div>
                    <div className="bg-background p-2">
                      <Image
                        src={image.url}
                        alt={t("imagePreview", { index: index + 1 })}
                        width={EXPORT_WIDTH}
                        height={720}
                        unoptimized
                        className="h-auto w-full rounded-xl border border-[color:var(--aqt-border)]"
                      />
                    </div>
                  </Card>
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
              bucketKeys={bucketKeys}
              ontology={ontology}
            />
          ))}
          <BalanceImageCaptureFrame
            refCallback={(node) => {
              fullImageRef.current = node;
            }}
            entries={payload.teams.map((team, teamIndex) => ({ team, teamIndex }))}
            divisionGrid={divisionGrid}
            bucketKeys={bucketKeys}
            ontology={ontology}
          />
        </div>
      ) : null}
    </>
  );
}

function BalanceImageCaptureFrame({
  refCallback,
  entries,
  divisionGrid,
  bucketKeys,
  ontology
}: Readonly<{
  refCallback: (node: HTMLDivElement | null) => void;
  entries: TeamExportEntry[];
  divisionGrid: DivisionGrid;
  bucketKeys: BalancerRosterKey[];
  ontology: RoleOntology | null;
}>) {
  return (
    <div
      ref={refCallback}
      className="mb-6 bg-[color:var(--aqt-bg)] p-4 text-[color:var(--aqt-fg)]"
      style={{ width: EXPORT_WIDTH }}
    >
      <div className="grid grid-cols-5 gap-3">
        {entries.map(({ team, teamIndex }) => (
          <BalanceExportTeamCard
            key={`${team.id}-${teamIndex}`}
            team={team}
            teamIndex={teamIndex}
            divisionGrid={divisionGrid}
            bucketKeys={bucketKeys}
            ontology={ontology}
          />
        ))}
      </div>
    </div>
  );
}

function BalanceExportTeamCard({
  team,
  teamIndex,
  divisionGrid,
  bucketKeys,
  ontology
}: Readonly<{
  team: InternalBalanceTeam;
  teamIndex: number;
  divisionGrid: DivisionGrid;
  bucketKeys: BalancerRosterKey[];
  ontology: RoleOntology | null;
}>) {
  const t = useTranslations("balancerTool.page.imageExport");
  const slotLabel = useSlotLabel(ontology);

  return (
    <div className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] shadow-[0_16px_48px_rgba(0,0,0,0.24)]">
      <BalanceTeamHeader team={team} teamIndex={teamIndex} />

      <Table className="min-w-90" wrapperClassName="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 w-13 px-4">{t("role")}</TableHead>
            <TableHead className="h-8 min-w-45 px-0">{t("player")}</TableHead>
            <TableHead className="h-8 w-18 text-center">{t("rank")}</TableHead>
            <TableHead className="h-8 w-22 px-3 text-center">{t("prefs")}</TableHead>
          </TableRow>
        </TableHeader>
        {bucketKeys.map((roleKey) => (
          <TableBody key={`${team.id}-${roleKey}`} className="[&_tr:last-child]:border-b">
            {team.roster[roleKey].map((player) => (
              <TableRow key={player.uuid}>
                <TableCell className="w-13 px-4 py-2.5">
                  <div className="flex justify-center">
                    <PlayerRoleIcon role={roleKey} ontology={ontology} size={18} />
                  </div>
                </TableCell>
                <TableCell className="min-w-45 py-2.5 pl-0 pr-2">
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
                      <Eyebrow tone="dim" className="truncate">
                        {formatSubRoleLabel(player.sub_role)}
                      </Eyebrow>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="w-18 py-2.5">
                  <ExportDivisionIcon divisionGrid={divisionGrid} rank={player.assigned_rating} />
                </TableCell>
                <TableCell className="w-22 px-3 py-2.5">
                  <div className="flex items-center justify-center gap-1">
                    {player.role_preferences.length > 0 ? (
                      player.role_preferences.slice(0, 3).map((preference, index) => (
                        <span
                          key={`${player.uuid}-${preference}-${index}`}
                          className="flex items-center justify-center opacity-85"
                        >
                          <PlayerRoleIcon role={preference} ontology={ontology} size={14} />
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-[color:var(--aqt-fg-faint)]">-</span>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}

            {team.roster[roleKey].length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className={cn(eyebrowClass(), "px-3 py-2.5 text-center")}
                >
                  {t("emptyRole", { role: slotLabel(roleKey).toLowerCase() })}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        ))}
      </Table>
    </div>
  );
}

function ExportDivisionIcon({ divisionGrid, rank }: Readonly<{ divisionGrid: DivisionGrid; rank: number }>) {
  const t = useTranslations("balancerTool.page.imageExport");
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const src = getDivisionIconSrc(divisionGrid, division);
  const label = getDivisionLabel(divisionGrid, division);

  if (!src || division == null) {
    return <div className="text-center text-xs text-[color:var(--aqt-fg-faint)]">-</div>;
  }

  return (
    <div className="flex justify-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={label ?? t("division", { division })}
        width={26}
        height={26}
        loading="eager"
        decoding="async"
      />
    </div>
  );
}
