"use client";

import { useState, useRef, useEffect } from "react";
import { Pencil, Check, X, Loader2, ArrowRightLeft } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import adminService from "@/services/admin.service";
import { SocialAccountsEditor } from "@/components/social/SocialAccountsEditor";
import { revalidateUser } from "@/app/actions/users";
import { notify } from "@/lib/notify";
import { MAX_AVATAR_BYTES } from "@/lib/avatar";
import type { User } from "@/types/user.types";

// ─── Avatar section ─────────────────────────────────────────────────────────

interface AvatarSectionProps {
  user: User;
  canEdit: boolean;
  onUserUpdated: (user: User) => void;
}

function AvatarSection({ user, canEdit, onUserUpdated }: AvatarSectionProps) {
  const queryClient = useQueryClient();

  const uploadMutation = useMutation({
    mutationFn: (file: File) => adminService.uploadUserAvatar(user.id, file),
    onSuccess: (updatedUser: User) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(updatedUser);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteUserAvatar(user.id),
    onSuccess: (updatedUser: User) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(updatedUser);
    },
  });

  const isPending = uploadMutation.isPending || deleteMutation.isPending;

  return (
    <div className="flex flex-col items-center gap-3">
      <EditableAvatar
        src={user.avatar_url}
        name={user.name}
        size={80}
        editable={canEdit}
        busy={isPending}
        onSelectFile={(file) => uploadMutation.mutate(file)}
        onDelete={user.avatar_url ? () => deleteMutation.mutate() : undefined}
        maxSizeBytes={MAX_AVATAR_BYTES}
        onError={(message) => notify.error(message)}
      />

      {(uploadMutation.isError || deleteMutation.isError) && (
        <p className="text-xs text-destructive text-center max-w-[200px]">
          {(uploadMutation.error ?? deleteMutation.error) instanceof Error
            ? ((uploadMutation.error ?? deleteMutation.error) as Error).message
            : "Avatar operation failed"}
        </p>
      )}
    </div>
  );
}

// ─── User name edit section ─────────────────────────────────────────────────

interface NameSectionProps {
  user: User;
  canEdit: boolean;
  onUserUpdated: (user: User) => void;
}

function NameSection({ user, canEdit, onUserUpdated }: NameSectionProps) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(user.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setTimeout(() => inputRef.current?.select(), 0);
    }
  }, [editing]);

  const updateMutation = useMutation({
    mutationFn: () => adminService.updateUser(user.id, { name }),
    onSuccess: (updatedUser: User) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(updatedUser);
      setEditing(false);
    },
  });

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === user.name) {
      setEditing(false);
      setName(user.name);
      return;
    }
    updateMutation.mutate();
  };

  const handleCancel = () => {
    setEditing(false);
    setName(user.name);
    updateMutation.reset();
  };

  const handleStartEditing = () => {
    setName(user.name);
    updateMutation.reset();
    setEditing(true);
  };

  if (editing) {
    return (
      <div className="space-y-2">
        <Label htmlFor="player-name" className="text-xs text-muted-foreground">
          Player Name
        </Label>
        <div className="flex items-center gap-2">
          <Input
            id="player-name"
            ref={inputRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") handleCancel();
            }}
            disabled={updateMutation.isPending}
            className="h-9 flex-1"
            autoFocus
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-green-500 hover:text-green-400 hover:bg-green-500/10"
            onClick={handleSave}
            disabled={updateMutation.isPending || !name.trim()}
            aria-label="Save name"
          >
            {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={handleCancel}
            disabled={updateMutation.isPending}
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {updateMutation.isError && updateMutation.error instanceof Error && (
          <p className="text-xs text-destructive">{updateMutation.error.message}</p>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 group">
      <h3 className="text-lg font-semibold truncate">{user.name}</h3>
      {canEdit && (
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={handleStartEditing}
          aria-label="Edit name"
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

// ─── Main dialog ────────────────────────────────────────────────────────────

interface PlayerProfileDialogProps {
  user: User;
  onClose: () => void;
  /** Avatar + name editing (user.update). */
  canEdit: boolean;
  canDelete: boolean;
  /** Full identity management — add/edit/delete/set-primary (superuser only). */
  canManageIdentity: boolean;
  /** Toggle per-workspace / global display visibility (user.read). */
  canSetVisibility: boolean;
  /** Current workspace for the per-workspace visibility toggle. */
  workspaceId: number | null;
  canMerge?: boolean;
  onMergeRequested?: (user: User) => void;
}

export function PlayerProfileDialog({
  user: initialUser,
  onClose,
  canEdit,
  canDelete,
  canManageIdentity,
  canSetVisibility,
  workspaceId,
  canMerge = false,
  onMergeRequested,
}: PlayerProfileDialogProps) {
  const [user, setUser] = useState(initialUser);

  // Every section updates local state through this; also bust the Next Data
  // Cache so users/[slug], the list and search reflect the change immediately.
  const handleUserUpdated = (updated: User) => {
    void revalidateUser(updated.id);
    setUser(updated);
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>Player Profile</DialogTitle>
          <DialogDescription>Manage player profile, avatar, and social identities.</DialogDescription>
        </DialogHeader>

        {/* ── Avatar + Name header ──────────────────────── */}
        <div className="flex flex-col items-center gap-3 pb-4 border-b border-border/40">
          <AvatarSection user={user} canEdit={canEdit} onUserUpdated={handleUserUpdated} />
          <NameSection user={user} canEdit={canEdit} onUserUpdated={handleUserUpdated} />
          <span className="text-xs text-muted-foreground tabular-nums">ID: {user.id}</span>
          {canMerge && onMergeRequested ? (
            <Button type="button" variant="outline" size="sm" onClick={() => onMergeRequested(user)}>
              <ArrowRightLeft className="mr-2 h-4 w-4" />
              Merge Into Another Profile
            </Button>
          ) : null}
        </div>

        {/* ── Social identities ─────────────────────────── */}
        <div className="pt-2">
          <div className="flex items-center gap-2 mb-3">
            <h4 className="text-sm font-medium text-muted-foreground">Social Identities</h4>
            <Badge variant="outline" className="tabular-nums font-normal text-xs">
              {user.social_accounts?.length ?? 0}
            </Badge>
          </div>
          <SocialAccountsEditor
            userId={user.id}
            accounts={user.social_accounts ?? []}
            canManage={canManageIdentity}
            canSetVisibility={canSetVisibility}
            workspaceId={workspaceId}
            onUserUpdated={handleUserUpdated}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
