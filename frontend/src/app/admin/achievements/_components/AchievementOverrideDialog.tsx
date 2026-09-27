"use client";

import { AchievementCombobox } from "@/components/admin/achievements/AchievementCombobox";
import { TournamentCombobox } from "@/components/admin/TournamentCombobox";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AchievementRule } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

/** The draft an admin is filling in, before it becomes an override. */
export interface OverrideDraftState {
  userId?: number;
  userName: string;
  ruleId?: number;
  action: "grant" | "revoke";
  reason: string;
  tournamentId?: number;
}

export function AchievementOverrideDialog({
  open,
  onOpenChange,
  rules,
  tournaments,
  draft,
  onDraftChange,
  onSubmit,
  isSaving,
  formError,
  saveError,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rules: AchievementRule[];
  tournaments: Tournament[];
  draft: OverrideDraftState;
  onDraftChange: (next: OverrideDraftState) => void;
  onSubmit: () => void;
  isSaving: boolean;
  formError: string | null;
  saveError?: string;
}>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Manual achievement override</DialogTitle>
          <DialogDescription>
            Grant or revoke an achievement for one player. The override survives future
            evaluation runs, so record why it was needed.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="override-user">User</Label>
            <UserSearchCombobox
              id="override-user"
              value={draft.userId}
              selectedName={draft.userName}
              onSelect={(user) =>
                onDraftChange({ ...draft, userId: user?.id, userName: user?.name ?? "" })
              }
              allowClear
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="override-achievement">Achievement</Label>
            <AchievementCombobox
              id="override-achievement"
              rules={rules}
              value={draft.ruleId}
              onSelect={(rule) => onDraftChange({ ...draft, ruleId: rule?.id })}
              allowClear
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="override-action">Action</Label>
              <Select
                value={draft.action}
                onValueChange={(v) => onDraftChange({ ...draft, action: v as "grant" | "revoke" })}
              >
                <SelectTrigger id="override-action">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">Grant</SelectItem>
                  <SelectItem value="revoke">Revoke</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="override-tournament">Tournament (optional)</Label>
              <TournamentCombobox
                id="override-tournament"
                tournaments={tournaments}
                value={draft.tournamentId}
                onSelect={(t) => onDraftChange({ ...draft, tournamentId: t?.id })}
                placeholder="None"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="override-reason">Reason</Label>
            <Textarea
              id="override-reason"
              value={draft.reason}
              onChange={(e) => onDraftChange({ ...draft, reason: e.target.value })}
              placeholder="Why is this being granted or revoked by hand?"
            />
          </div>

          {formError && <p className="text-sm text-danger">{formError}</p>}
          {saveError && (
            <p className="text-sm text-danger">
              The override could not be saved: {saveError}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isSaving}>
            {isSaving
              ? "Saving…"
              : draft.action === "grant"
                ? "Grant achievement"
                : "Revoke achievement"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
