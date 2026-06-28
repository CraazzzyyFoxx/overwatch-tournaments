"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Pencil, Plus, Star, Trash2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, SOCIAL_PROVIDER_ORDER, socialAccountsForProvider } from "@/lib/social-providers";
import adminService from "@/services/admin.service";
import type { SocialAccount, SocialProvider, User } from "@/types/user.types";

interface SocialAccountsEditorProps {
  userId: number;
  accounts: SocialAccount[];
  canEdit: boolean;
  canDelete: boolean;
  onUserUpdated: (user: User) => void;
}

// ─── Single account row (view / inline edit) ─────────────────────────────────

interface AccountRowProps {
  account: SocialAccount;
  userId: number;
  canEdit: boolean;
  canDelete: boolean;
  onUserUpdated: (user: User) => void;
}

function AccountRow({ account, userId, canEdit, canDelete, onUserUpdated }: AccountRowProps) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(account.username);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = getSocialProviderConfig(account.provider);

  const startEdit = () => {
    setEditValue(account.username);
    setEditing(true);
  };

  useEffect(() => {
    if (editing) {
      setTimeout(() => inputRef.current?.select(), 0);
    }
  }, [editing]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });

  const updateMutation = useMutation({
    mutationFn: () => adminService.updateSocialAccount(userId, account.id, { username: editValue.trim() }),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setEditing(false);
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteSocialAccount(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setDeleteOpen(false);
    }
  });

  const primaryMutation = useMutation({
    mutationFn: () => adminService.setSocialAccountPrimary(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
    }
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
      <div className="flex items-center gap-2">
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
        {updateMutation.isError && updateMutation.error instanceof Error && (
          <span className="max-w-[180px] truncate text-xs text-destructive">{updateMutation.error.message}</span>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="group flex items-center gap-2 rounded-lg px-3 py-2 transition-colors hover:bg-muted/50">
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
          <SocialIcon provider={account.provider} size={14} />
        </span>
        <span className="flex-1 truncate text-sm font-medium">{account.username}</span>
        {account.is_verified && (
          <span className="inline-flex items-center gap-0.5 text-xs text-[color:var(--aqt-teal,#2dd4bf)]" title="Verified via OAuth">
            <Check className="h-3.5 w-3.5" />
          </span>
        )}
        {account.is_primary ? (
          <Star className="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-400" aria-label="Primary" />
        ) : (
          canEdit && (
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
        {(canEdit || canDelete) && (
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            {canEdit && (
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={startEdit} aria-label={`Edit ${account.username}`}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            )}
            {canDelete && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive/70 hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setDeleteOpen(true)}
                aria-label={`Delete ${account.username}`}
              >
                {deleteMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </Button>
            )}
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

interface AddAccountRowProps {
  provider: SocialProvider;
  userId: number;
  onUserUpdated: (user: User) => void;
}

function AddAccountRow({ provider, userId, onUserUpdated }: AddAccountRowProps) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const config = getSocialProviderConfig(provider);

  const addMutation = useMutation({
    mutationFn: () => adminService.addSocialAccount(userId, { provider, username: value.trim() }),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(user);
      setValue("");
    }
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

// ─── Editor (provider tabs over social_accounts) ─────────────────────────────

/** Unified add/edit/delete/set-primary editor for a player's social accounts. */
export function SocialAccountsEditor({ userId, accounts, canEdit, canDelete, onUserUpdated }: SocialAccountsEditorProps) {
  const countByProvider = (provider: SocialProvider) => socialAccountsForProvider(accounts, provider).length;
  const [defaultTab] = useState<SocialProvider>(() =>
    SOCIAL_PROVIDER_ORDER.reduce((best, p) => (countByProvider(p) > countByProvider(best) ? p : best), SOCIAL_PROVIDER_ORDER[0])
  );

  return (
    <Tabs defaultValue={defaultTab} className="w-full">
      <TabsList className="flex w-full flex-wrap">
        {SOCIAL_PROVIDER_ORDER.map((provider) => {
          const config = getSocialProviderConfig(provider);
          const count = countByProvider(provider);
          return (
            <TabsTrigger key={provider} value={provider} className="gap-1.5">
              <SocialIcon provider={provider} size={16} />
              <span className="hidden sm:inline">{config.label}</span>
              {count > 0 && (
                <Badge variant="secondary" className="h-5 min-w-5 px-1.5 text-xs tabular-nums">
                  {count}
                </Badge>
              )}
            </TabsTrigger>
          );
        })}
      </TabsList>

      {SOCIAL_PROVIDER_ORDER.map((provider) => {
        const config = getSocialProviderConfig(provider);
        const items = socialAccountsForProvider(accounts, provider);
        return (
          <TabsContent key={provider} value={provider} className="mt-4 space-y-3">
            {items.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">No {config.label} identities yet</p>
            )}
            {items.length > 0 && (
              <div className="space-y-1">
                {items.map((account) => (
                  <AccountRow
                    key={account.id}
                    account={account}
                    userId={userId}
                    canEdit={canEdit}
                    canDelete={canDelete}
                    onUserUpdated={onUserUpdated}
                  />
                ))}
              </div>
            )}
            {canEdit && <AddAccountRow provider={provider} userId={userId} onUserUpdated={onUserUpdated} />}
          </TabsContent>
        );
      })}
    </Tabs>
  );
}
