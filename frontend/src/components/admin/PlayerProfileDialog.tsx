"use client";

import { useState, useRef, useEffect } from "react";
import Image from "next/image";
import {
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  Loader2,
  Camera,
  ImageOff,
  ArrowRightLeft,
} from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";

import adminService from "@/services/admin.service";
import type {
  User,
  UserDiscord,
  UserBattleTag,
  UserTwitch,
} from "@/types/user.types";

// ─── Platform config ────────────────────────────────────────────────────────

type IdentityItem = UserDiscord | UserBattleTag | UserTwitch;

interface PlatformConfig {
  key: "discord" | "battle_tag" | "twitch";
  label: string;
  icon: string;
  placeholder: string;
  color: string;
  getDisplayName: (item: IdentityItem) => string;
  getAddPayload: (value: string) => Record<string, string>;
  getUpdatePayload: (value: string) => Record<string, string>;
  addFn: (userId: number, data: Record<string, string>) => Promise<User>;
  updateFn: (
    userId: number,
    identityId: number,
    data: Record<string, string>,
  ) => Promise<User>;
  deleteFn: (userId: number, identityId: number) => Promise<void>;
}

const PLATFORMS: PlatformConfig[] = [
  {
    key: "discord",
    label: "Discord",
    icon: "/discord.png",
    placeholder: "username",
    color: "#5865F2",
    getDisplayName: (item) => (item as UserDiscord).name,
    getAddPayload: (value) => ({ name: value }),
    getUpdatePayload: (value) => ({ name: value }),
    addFn: (userId, data) =>
      adminService.addDiscordIdentity(userId, data as { name: string }),
    updateFn: (userId, id, data) =>
      adminService.updateDiscordIdentity(
        userId,
        id,
        data as { name: string },
      ),
    deleteFn: (userId, id) => adminService.deleteDiscordIdentity(userId, id),
  },
  {
    key: "battle_tag",
    label: "BattleTag",
    icon: "/battlenet.svg",
    placeholder: "Name#1234",
    color: "#148EFF",
    getDisplayName: (item) => (item as UserBattleTag).battle_tag,
    getAddPayload: (value) => ({ battle_tag: value }),
    getUpdatePayload: (value) => ({ battle_tag: value }),
    addFn: (userId, data) =>
      adminService.addBattleTagIdentity(
        userId,
        data as { battle_tag: string },
      ),
    updateFn: (userId, id, data) =>
      adminService.updateBattleTagIdentity(
        userId,
        id,
        data as { battle_tag: string },
      ),
    deleteFn: (userId, id) => adminService.deleteBattleTagIdentity(userId, id),
  },
  {
    key: "twitch",
    label: "Twitch",
    icon: "/twitch.png",
    placeholder: "username",
    color: "#9146FF",
    getDisplayName: (item) => (item as UserTwitch).name,
    getAddPayload: (value) => ({ name: value }),
    getUpdatePayload: (value) => ({ name: value }),
    addFn: (userId, data) =>
      adminService.addTwitchIdentity(userId, data as { name: string }),
    updateFn: (userId, id, data) =>
      adminService.updateTwitchIdentity(
        userId,
        id,
        data as { name: string },
      ),
    deleteFn: (userId, id) => adminService.deleteTwitchIdentity(userId, id),
  },
];

// ─── Identity row (view / edit) ─────────────────────────────────────────────

interface IdentityRowProps {
  identity: IdentityItem;
  platform: PlatformConfig;
  userId: number;
  canEdit: boolean;
  canDelete: boolean;
  onUserUpdated: (user: User) => void;
  onIdentityDeleted: (platformKey: string, identityId: number) => void;
}

function IdentityRow({
  identity,
  platform,
  userId,
  canEdit,
  canDelete,
  onUserUpdated,
  onIdentityDeleted,
}: IdentityRowProps) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const displayName = platform.getDisplayName(identity);

  useEffect(() => {
    if (editing) {
      setTimeout(() => inputRef.current?.select(), 0);
    }
  }, [editing]);

  const updateMutation = useMutation({
    mutationFn: () =>
      platform.updateFn(
        userId,
        identity.id,
        platform.getUpdatePayload(editValue),
      ),
    onSuccess: (updatedUser: User) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(updatedUser);
      setEditing(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => platform.deleteFn(userId, identity.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onIdentityDeleted(platform.key, identity.id);
      setDeleteOpen(false);
    },
  });

  const handleSave = () => {
    const trimmed = editValue.trim();
    if (!trimmed || trimmed === displayName) {
      setEditing(false);
      return;
    }
    updateMutation.mutate();
  };

  const handleCancel = () => {
    setEditing(false);
    updateMutation.reset();
  };

  const handleStartEditing = () => {
    setEditValue(displayName);
    updateMutation.reset();
    setEditing(true);
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2 group">
        <Input
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
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
          disabled={updateMutation.isPending || !editValue.trim()}
          aria-label="Save"
        >
          {updateMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
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
        {updateMutation.isError && updateMutation.error instanceof Error && (
          <span className="text-xs text-destructive truncate max-w-[180px]">
            {updateMutation.error.message}
          </span>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-2 group rounded-lg px-3 py-2 transition-colors hover:bg-muted/50">
        <span
          className="inline-block h-2 w-2 rounded-full shrink-0"
          style={{ backgroundColor: platform.color }}
        />
        <span className="flex-1 text-sm font-medium truncate">
          {displayName}
        </span>
        {(canEdit || canDelete) && (
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {canEdit && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleStartEditing}
                aria-label={`Edit ${displayName}`}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            )}
            {canDelete && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive/70 hover:text-destructive hover:bg-destructive/10"
                onClick={() => setDeleteOpen(true)}
                aria-label={`Delete ${displayName}`}
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
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
        title={`Remove ${displayName}?`}
        description={`This will remove the ${platform.label} identity "${displayName}" from this player.`}
      />
    </>
  );
}

// ─── Add identity row ───────────────────────────────────────────────────────

interface AddIdentityRowProps {
  platform: PlatformConfig;
  userId: number;
  onUserUpdated: (user: User) => void;
}

function AddIdentityRow({
  platform,
  userId,
  onUserUpdated,
}: AddIdentityRowProps) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const addMutation = useMutation({
    mutationFn: () =>
      platform.addFn(userId, platform.getAddPayload(value.trim())),
    onSuccess: (updatedUser: User) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onUserUpdated(updatedUser);
      setValue("");
      inputRef.current?.focus();
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
          ref={inputRef}
          placeholder={`Add ${platform.placeholder}...`}
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
          aria-label={`Add ${platform.label} identity`}
        >
          {addMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
        </Button>
      </div>
      {addMutation.isError && addMutation.error instanceof Error && (
        <p className="text-xs text-destructive px-1">
          {addMutation.error.message}
        </p>
      )}
    </div>
  );
}

// ─── Platform tab content ───────────────────────────────────────────────────

interface PlatformTabProps {
  platform: PlatformConfig;
  items: IdentityItem[];
  userId: number;
  canEdit: boolean;
  canDelete: boolean;
  onUserUpdated: (user: User) => void;
  onIdentityDeleted: (platformKey: string, identityId: number) => void;
}

function PlatformTab({
  platform,
  items,
  userId,
  canEdit,
  canDelete,
  onUserUpdated,
  onIdentityDeleted,
}: PlatformTabProps) {
  return (
    <div className="space-y-3">
      {items.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-6">
          No {platform.label} identities yet
        </p>
      )}
      {items.length > 0 && (
        <div className="space-y-1">
          {items.map((item) => (
            <IdentityRow
              key={item.id}
              identity={item}
              platform={platform}
              userId={userId}
              canEdit={canEdit}
              canDelete={canDelete}
              onUserUpdated={onUserUpdated}
              onIdentityDeleted={onIdentityDeleted}
            />
          ))}
        </div>
      )}
      {canEdit && (
        <AddIdentityRow
          platform={platform}
          userId={userId}
          onUserUpdated={onUserUpdated}
        />
      )}
    </div>
  );
}

// ─── Tab trigger with icon and count ────────────────────────────────────────

interface PlatformTabTriggerProps {
  platform: PlatformConfig;
  count: number;
}

function PlatformTabTrigger({ platform, count }: PlatformTabTriggerProps) {
  return (
    <TabsTrigger
      value={platform.key}
      className="gap-1.5 data-[state=active]:gap-1.5"
    >
      <Image src={platform.icon} width={16} height={16} alt={platform.label} />
      <span className="hidden sm:inline">{platform.label}</span>
      {count > 0 && (
        <Badge
          variant="secondary"
          className="h-5 min-w-5 px-1.5 text-xs tabular-nums"
        >
          {count}
        </Badge>
      )}
    </TabsTrigger>
  );
}

// ─── Avatar section ─────────────────────────────────────────────────────────

interface AvatarSectionProps {
  user: User;
  canEdit: boolean;
  onUserUpdated: (user: User) => void;
}

function AvatarSection({ user, canEdit, onUserUpdated }: AvatarSectionProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadMutation.mutate(file);
    }
    e.target.value = "";
  };

  const initials = user.name
    .split(/[#\s]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");

  const isPending = uploadMutation.isPending || deleteMutation.isPending;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative group">
        <Avatar className="h-20 w-20 text-xl">
          <AvatarImage src={user.avatar_url ?? undefined} alt={user.name} />
          <AvatarFallback className="bg-muted text-muted-foreground font-medium">
            {isPending ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              initials || "?"
            )}
          </AvatarFallback>
        </Avatar>
        {canEdit && !isPending && (
          <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer">
            <Camera className="h-5 w-5 text-white" />
          </div>
        )}
        {canEdit && !isPending && (
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer rounded-full"
            onChange={handleFileChange}
          />
        )}
      </div>

      {canEdit && user.avatar_url && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs text-destructive/70 hover:text-destructive hover:bg-destructive/10"
          onClick={() => deleteMutation.mutate()}
          disabled={isPending}
        >
          <ImageOff className="h-3.5 w-3.5 mr-1.5" />
          Remove avatar
        </Button>
      )}

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
            {updateMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
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
          <p className="text-xs text-destructive">
            {updateMutation.error.message}
          </p>
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
  canEdit: boolean;
  canDelete: boolean;
  canMerge?: boolean;
  onMergeRequested?: (user: User) => void;
}

export function PlayerProfileDialog({
  user: initialUser,
  onClose,
  canEdit,
  canDelete,
  canMerge = false,
  onMergeRequested,
}: PlayerProfileDialogProps) {
  const [user, setUser] = useState(initialUser);

  const handleUserUpdated = (updatedUser: User) => {
    setUser(updatedUser);
  };

  const handleIdentityDeleted = (
    platformKey: string,
    identityId: number,
  ) => {
    setUser((prev) => ({
      ...prev,
      [platformKey]: (
        prev[platformKey as keyof User] as IdentityItem[]
      ).filter((item) => item.id !== identityId),
    }));
  };

  const itemsMap: Record<string, IdentityItem[]> = {
    discord: user.discord ?? [],
    battle_tag: user.battle_tag ?? [],
    twitch: user.twitch ?? [],
  };

  const totalCount = Object.values(itemsMap).reduce(
    (sum, arr) => sum + arr.length,
    0,
  );

  const [defaultTab] = useState(() =>
    PLATFORMS.reduce((best, p) =>
      (itemsMap[p.key]?.length ?? 0) > (itemsMap[best.key]?.length ?? 0)
        ? p
        : best,
    ).key,
  );

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>Player Profile</DialogTitle>
          <DialogDescription>
            Manage player profile, avatar, and platform identities.
          </DialogDescription>
        </DialogHeader>

        {/* ── Avatar + Name header ──────────────────────── */}
        <div className="flex flex-col items-center gap-3 pb-4 border-b border-border/40">
          <AvatarSection
            user={user}
            canEdit={canEdit}
            onUserUpdated={handleUserUpdated}
          />
          <NameSection
            user={user}
            canEdit={canEdit}
            onUserUpdated={handleUserUpdated}
          />
          <span className="text-xs text-muted-foreground tabular-nums">
            ID: {user.id}
          </span>
          {canMerge && onMergeRequested ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onMergeRequested(user)}
            >
              <ArrowRightLeft className="mr-2 h-4 w-4" />
              Merge Into Another Profile
            </Button>
          ) : null}
        </div>

        {/* ── Identities tabs ──────────────────────────── */}
        <div className="pt-2">
          <div className="flex items-center gap-2 mb-3">
            <h4 className="text-sm font-medium text-muted-foreground">
              Platform Identities
            </h4>
            <Badge
              variant="outline"
              className="tabular-nums font-normal text-xs"
            >
              {totalCount}
            </Badge>
          </div>

          <Tabs defaultValue={defaultTab} className="w-full">
            <TabsList className="w-full">
              {PLATFORMS.map((platform) => (
                <PlatformTabTrigger
                  key={platform.key}
                  platform={platform}
                  count={itemsMap[platform.key]?.length ?? 0}
                />
              ))}
            </TabsList>

            {PLATFORMS.map((platform) => (
              <TabsContent
                key={platform.key}
                value={platform.key}
                className="mt-4"
              >
                <PlatformTab
                  platform={platform}
                  items={itemsMap[platform.key] ?? []}
                  userId={user.id}
                  canEdit={canEdit}
                  canDelete={canDelete}
                  onUserUpdated={handleUserUpdated}
                  onIdentityDeleted={handleIdentityDeleted}
                />
              </TabsContent>
            ))}
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
}
