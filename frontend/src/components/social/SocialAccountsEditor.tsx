"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Eye, EyeOff, Loader2, Pencil, Plus, Star, Trash2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, SOCIAL_PROVIDER_ORDER, socialAccountsForProvider } from "@/lib/social-providers";
import adminService from "@/services/admin.service";
import { cn } from "@/lib/utils";
import type { SocialAccount, SocialProvider, User } from "@/types/user.types";

interface SocialAccountsEditorProps {
  userId: number;
  accounts: SocialAccount[];
  /** Superuser: full add/edit/delete/set-primary management. */
  canManage: boolean;
  /** Read rights: toggle per-workspace / global display visibility. */
  canSetVisibility: boolean;
  /** Current workspace for the per-workspace visibility toggle (null = none). */
  workspaceId: number | null;
  onUserUpdated: (user: User) => void;
}

// ─── Visibility toggles (global + current workspace) ─────────────────────────

interface VisibilityControlsProps {
  account: SocialAccount;
  userId: number;
  workspaceId: number | null;
  onUserUpdated: (user: User) => void;
}

function VisibilityControls({ account, userId, workspaceId, onUserUpdated }: VisibilityControlsProps) {
  const queryClient = useQueryClient();
  const globalVisible = account.visible_global ?? true;
  const workspaceVisible = workspaceId != null && (account.visible_workspace_ids ?? []).includes(workspaceId);

  const mutation = useMutation({
    mutationFn: (vars: { workspace_id: number | null; visible: boolean }) =>
      adminService.setSocialAccountVisibility(userId, account.id, vars),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(user);
    },
  });

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-6 text-xs text-muted-foreground">
      <label className="flex cursor-pointer select-none items-center gap-1.5">
        <Switch
          checked={globalVisible}
          onCheckedChange={(v) => mutation.mutate({ workspace_id: null, visible: v })}
          disabled={mutation.isPending}
          className="scale-75"
        />
        <Eye className="h-3 w-3" /> Profile
      </label>
      {workspaceId != null && (
        <label className="flex cursor-pointer select-none items-center gap-1.5">
          <Switch
            checked={workspaceVisible}
            onCheckedChange={(v) => mutation.mutate({ workspace_id: workspaceId, visible: v })}
            disabled={mutation.isPending}
            className="scale-75"
          />
          <EyeOff className="h-3 w-3" /> This workspace
        </label>
      )}
      {mutation.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
    </div>
  );
}

// ─── Single account row (view / inline edit) ─────────────────────────────────

interface AccountRowProps {
  account: SocialAccount;
  userId: number;
  canManage: boolean;
  canSetVisibility: boolean;
  workspaceId: number | null;
  onUserUpdated: (user: User) => void;
}

function AccountRow({ account, userId, canManage, canSetVisibility, workspaceId, onUserUpdated }: AccountRowProps) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(account.username);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = getSocialProviderConfig(account.provider);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });

  useEffect(() => {
    if (editing) setTimeout(() => inputRef.current?.select(), 0);
  }, [editing]);

  const updateMutation = useMutation({
    mutationFn: () => adminService.updateSocialAccount(userId, account.id, { username: editValue.trim() }),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setEditing(false);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteSocialAccount(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setDeleteOpen(false);
    },
  });
  const primaryMutation = useMutation({
    mutationFn: () => adminService.setSocialAccountPrimary(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
    },
  });

  const handleSave = () => {
    const trimmed = editValue.trim();
    if (!trimmed || trimmed === account.username) {
      setEditing(false);
      return;
    }
    updateMutation.mutate();
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2 px-1">
        <Input
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
            if (e.key === "Escape") setEditing(false);
          }}
          disabled={updateMutation.isPending}
          className="h-9 flex-1"
          autoFocus
        />
        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 text-green-500 hover:bg-green-500/10 hover:text-green-400"
          onClick={handleSave}
          disabled={updateMutation.isPending || !editValue.trim()}
          aria-label="Save"
        >
          {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 text-muted-foreground hover:text-foreground"
          onClick={() => setEditing(false)}
          disabled={updateMutation.isPending}
          aria-label="Cancel"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="rounded-lg px-2 py-1.5 transition-colors hover:bg-muted/50">
        <div className="group flex items-center gap-2">
          <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
            <SocialIcon provider={account.provider} size={14} />
          </span>
          <span className="flex-1 truncate text-sm font-medium">{account.username}</span>
          {account.is_verified && (
            <Check
              className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-teal)]"
              aria-label="Verified via OAuth"
            />
          )}
          {account.is_primary ? (
            <Star className="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-400" aria-label="Primary" />
          ) : (
            canManage && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
                onClick={() => primaryMutation.mutate()}
                disabled={primaryMutation.isPending}
                aria-label="Make primary"
                title="Make primary"
              >
                {primaryMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Star className="h-3.5 w-3.5" />}
              </Button>
            )
          )}
          {canManage && (
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => { setEditValue(account.username); setEditing(true); }} aria-label={`Edit ${account.username}`}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive/70 hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setDeleteOpen(true)}
                aria-label={`Delete ${account.username}`}
              >
                {deleteMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </Button>
            </div>
          )}
        </div>
        {(canManage || canSetVisibility) && (
          <div className="mt-1">
            <VisibilityControls account={account} userId={userId} workspaceId={workspaceId} onUserUpdated={onUserUpdated} />
          </div>
        )}
      </div>
      <DeleteConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => deleteMutation.mutate()}
        isDeleting={deleteMutation.isPending}
        title={`Remove ${account.username}?`}
        description={`This will remove the ${config.label} identity "${account.username}" from this player.`}
      />
    </>
  );
}

// ─── Add row (per provider) ──────────────────────────────────────────────────

function AddAccountRow({ provider, userId, onUserUpdated }: { provider: SocialProvider; userId: number; onUserUpdated: (user: User) => void }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const config = getSocialProviderConfig(provider);

  const addMutation = useMutation({
    mutationFn: () => adminService.addSocialAccount(userId, { provider, username: value.trim() }),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(user);
      setValue("");
    },
  });

  const handleAdd = () => {
    if (!value.trim() || addMutation.isPending) return;
    addMutation.mutate();
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 px-1">
        <Input
          placeholder={`Add ${config.placeholder}...`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleAdd();
          }}
          disabled={addMutation.isPending}
          className="h-9 flex-1"
        />
        <Button
          size="icon"
          variant="outline"
          className="h-9 w-9 shrink-0"
          onClick={handleAdd}
          disabled={!value.trim() || addMutation.isPending}
          aria-label={`Add ${config.label}`}
        >
          {addMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        </Button>
      </div>
      {addMutation.isError && addMutation.error instanceof Error && (
        <p className="px-1 text-xs text-destructive">{addMutation.error.message}</p>
      )}
    </div>
  );
}

// ─── Editor (unified provider combobox over social_accounts) ─────────────────

/** Provider-combobox editor for a player's social accounts: pick a provider to
 *  see its linked accounts. Superusers manage them; others may toggle display. */
export function SocialAccountsEditor({
  userId,
  accounts,
  canManage,
  canSetVisibility,
  workspaceId,
  onUserUpdated,
}: SocialAccountsEditorProps) {
  const countByProvider = useMemo(() => {
    const map = {} as Record<SocialProvider, number>;
    for (const provider of SOCIAL_PROVIDER_ORDER) map[provider] = socialAccountsForProvider(accounts, provider).length;
    return map;
  }, [accounts]);

  const [provider, setProvider] = useState<SocialProvider>(() =>
    SOCIAL_PROVIDER_ORDER.reduce((best, p) => (countByProvider[p] > countByProvider[best] ? p : best), SOCIAL_PROVIDER_ORDER[0])
  );

  const config = getSocialProviderConfig(provider);
  const items = socialAccountsForProvider(accounts, provider);

  return (
    <div className="space-y-3">
      <Select value={provider} onValueChange={(v) => setProvider(v as SocialProvider)}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SOCIAL_PROVIDER_ORDER.map((p) => {
            const pConfig = getSocialProviderConfig(p);
            const count = countByProvider[p];
            return (
              <SelectItem key={p} value={p}>
                <span className="flex items-center gap-2">
                  <SocialIcon provider={p} size={14} />
                  <span>{pConfig.label}</span>
                  {count > 0 && (
                    <span className="rounded bg-muted px-1.5 text-xs tabular-nums text-muted-foreground">{count}</span>
                  )}
                </span>
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>

      <div className={cn("space-y-1", items.length === 0 && "py-0")}>
        {items.length === 0 ? (
          <p className="py-5 text-center text-sm text-muted-foreground">No {config.label} identities yet</p>
        ) : (
          items.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              userId={userId}
              canManage={canManage}
              canSetVisibility={canSetVisibility}
              workspaceId={workspaceId}
              onUserUpdated={onUserUpdated}
            />
          ))
        )}
      </div>

      {canManage && <AddAccountRow provider={provider} userId={userId} onUserUpdated={onUserUpdated} />}
    </div>
  );
}
