"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { FileUp, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Encounter } from "@/types/encounter.types";

interface TournamentLogUploadDialogProps {
  tournamentId: number;
  encounters: Encounter[];
  trigger: ReactNode;
  initialEncounterId?: number | null;
  onUploaded?: () => void;
}

const NO_ENCOUNTER_VALUE = "none";

function getDuplicateFileNames(files: File[]) {
  const seen = new Set<string>();
  const duplicates = new Set<string>();

  for (const file of files) {
    if (seen.has(file.name)) {
      duplicates.add(file.name);
    }
    seen.add(file.name);
  }

  return Array.from(duplicates).sort();
}

export function TournamentLogUploadDialog({
  tournamentId,
  encounters,
  trigger,
  initialEncounterId = null,
  onUploaded
}: TournamentLogUploadDialogProps) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [selectedEncounterId, setSelectedEncounterId] = useState<string>(
    initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE
  );
  const duplicateFileNames = useMemo(() => getDuplicateFileNames(files), [files]);

  const uploadMutation = useMutation({
    mutationFn: () =>
      adminService.uploadMatchLogs({
        tournamentId,
        files,
        encounterId: selectedEncounterId === NO_ENCOUNTER_VALUE ? null : Number(selectedEncounterId)
      }),
    onSuccess: (result) => {
      onUploaded?.();
      setOpen(false);
      const uploadedCount = result.uploaded.length;
      const errorCount = result.errors.length;
      if (errorCount) {
        notify.error("Logs uploaded with errors", {
          description: `${uploadedCount} queued, ${errorCount} failed`
        });
      } else {
        notify.success("Logs queued", {
          description: `${uploadedCount} file${uploadedCount === 1 ? "" : "s"} queued for processing`
        });
      }
    }
  });

  const canSubmit =
    files.length > 0 && duplicateFileNames.length === 0 && !uploadMutation.isPending;

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      setSelectedEncounterId(
        initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE
      );
      setFiles([]);
      uploadMutation.reset();
    }
    setOpen(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Upload Match Logs</DialogTitle>
          <DialogDescription>
            Attach log files to this tournament and optionally mark the related encounter.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="admin-match-log-files">Files</Label>
            <Input
              id="admin-match-log-files"
              type="file"
              multiple
              accept=".log,.txt,.csv,text/plain,text/csv"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            {files.length ? (
              <p className="text-xs text-muted-foreground">
                {files.length} file{files.length === 1 ? "" : "s"} selected
              </p>
            ) : null}
            {duplicateFileNames.length ? (
              <p className="text-xs text-destructive">
                Duplicate file names: {duplicateFileNames.join(", ")}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="admin-match-log-encounter">Attached encounter</Label>
            <Select value={selectedEncounterId} onValueChange={setSelectedEncounterId}>
              <SelectTrigger id="admin-match-log-encounter">
                <SelectValue placeholder="No encounter" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_ENCOUNTER_VALUE}>No encounter</SelectItem>
                {encounters.map((encounter) => (
                  <SelectItem key={encounter.id} value={encounter.id.toString()}>
                    {encounter.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={uploadMutation.isPending}
          >
            Cancel
          </Button>
          <Button type="button" onClick={() => uploadMutation.mutate()} disabled={!canSubmit}>
            {uploadMutation.isPending ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <FileUp className="mr-2 size-4" />
            )}
            Upload
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
