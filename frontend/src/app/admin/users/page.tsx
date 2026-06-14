"use client";

import { useState } from "react";
import Image from "next/image";
import { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Plus, Minus, Pencil, Trash2, Upload, ArrowRightLeft } from "lucide-react";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { PlayerProfileDialog } from "@/components/admin/PlayerProfileDialog";
import { UserMergeDialog } from "@/components/admin/UserMergeDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import adminService from "@/services/admin.service";
import type { User } from "@/types/user.types";
import type { UserCreateInput, CsvUserImportParams } from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useWorkspaceStore } from "@/stores/workspace.store";


const defaultImportParams: CsvUserImportParams = {
  battle_tag_row: 1,
  discord_row: 2,
  twitch_row: 3,
  smurf_row: 4,
  start_row: 1,
  delimiter: ",",
  sheet_url: "",
};

interface ColumnStepperProps {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  required?: boolean;
}

function ColumnStepper({ label, value, onChange, required }: ColumnStepperProps) {
  const enabled = value != null;

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        {!required && (
          <Switch
            checked={enabled}
            onCheckedChange={(checked) => onChange(checked ? 1 : null)}
          />
        )}
        <span className={`text-sm font-medium ${!enabled ? "text-muted-foreground" : ""}`}>
          {label}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-8 w-8"
          disabled={!enabled || (value ?? 0) <= 1}
          onClick={() => onChange(Math.max(1, (value ?? 1) - 1))}
        >
          <Minus className="h-3 w-3" />
        </Button>
        <div className={`w-10 text-center tabular-nums text-sm font-medium ${!enabled ? "text-muted-foreground" : ""}`}>
          {enabled ? value : "—"}
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-8 w-8"
          disabled={!enabled}
          onClick={() => onChange((value ?? 0) + 1)}
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

interface CsvImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function CsvImportDialog({ open, onOpenChange }: CsvImportDialogProps) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<string>("file");
  const [file, setFile] = useState<File | null>(null);
  const [params, setParams] = useState<CsvUserImportParams>({ ...defaultImportParams });

  const importMutation = useMutation({
    mutationFn: () => {
      const submitParams = { ...params };
      if (tab === "file") {
        delete submitParams.sheet_url;
      }
      return adminService.bulkCreateUsersFromCsv(
        submitParams,
        tab === "file" ? file ?? undefined : undefined,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onOpenChange(false);
      setFile(null);
      setParams({ ...defaultImportParams });
    },
  });

  const canSubmit =
    (tab === "file" && file !== null) || (tab === "sheet" && !!params.sheet_url);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import Users from CSV</DialogTitle>
          <DialogDescription>
            Upload a CSV file or provide a Google Sheets link to bulk-create users.
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="file">CSV File</TabsTrigger>
            <TabsTrigger value="sheet">Google Sheets</TabsTrigger>
          </TabsList>

          <TabsContent value="file" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="csv-file">CSV File</Label>
              <Input
                id="csv-file"
                type="file"
                accept=".csv,.txt"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </TabsContent>

          <TabsContent value="sheet" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="sheet-url">Google Sheets URL</Label>
              <Input
                id="sheet-url"
                placeholder="https://docs.google.com/spreadsheets/d/..."
                value={params.sheet_url ?? ""}
                onChange={(e) => setParams({ ...params, sheet_url: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Sheet must be publicly accessible (or shared via link).
              </p>
            </div>
          </TabsContent>
        </Tabs>

        <div className="space-y-3 pt-2">
          <p className="text-sm font-medium">Column Mapping</p>
          <div className="space-y-2">
            <ColumnStepper
              label="BattleTag"
              value={params.battle_tag_row}
              onChange={(v) => setParams({ ...params, battle_tag_row: v ?? 1 })}
              required
            />
            <ColumnStepper
              label="Discord"
              value={params.discord_row}
              onChange={(v) => setParams({ ...params, discord_row: v })}
            />
            <ColumnStepper
              label="Twitch"
              value={params.twitch_row}
              onChange={(v) => setParams({ ...params, twitch_row: v })}
            />
            <ColumnStepper
              label="Smurf"
              value={params.smurf_row}
              onChange={(v) => setParams({ ...params, smurf_row: v })}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="start-row">Start Row</Label>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-9 w-9 shrink-0"
                disabled={(params.start_row ?? 0) <= 0}
                onClick={() => setParams({ ...params, start_row: Math.max(0, (params.start_row ?? 0) - 1) })}
              >
                <Minus className="h-3 w-3" />
              </Button>
              <div className="flex-1 text-center tabular-nums text-sm font-medium">
                {params.start_row ?? 0}
              </div>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={() => setParams({ ...params, start_row: (params.start_row ?? 0) + 1 })}
              >
                <Plus className="h-3 w-3" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Skip header rows (0 = no skip)
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="delimiter">Delimiter</Label>
            <Input
              id="delimiter"
              value={params.delimiter ?? ","}
              onChange={(e) =>
                setParams({ ...params, delimiter: e.target.value })
              }
            />
          </div>
        </div>

        {importMutation.error instanceof Error && (
          <p className="text-sm text-destructive">{importMutation.error.message}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => importMutation.mutate()}
            disabled={!canSubmit || importMutation.isPending}
          >
            {importMutation.isPending ? "Importing..." : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function UsersAdminPage() {
  const queryClient = useQueryClient();
  const { canAccessPermission, isSuperuser } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [profileUser, setProfileUser] = useState<User | null>(null);
  const [mergeUser, setMergeUser] = useState<User | null>(null);
  const [deletingUser, setDeletingUser] = useState<User | null>(null);
  const [createName, setCreateName] = useState("");
  const canCreate = canAccessPermission("user.create", workspaceId);
  const canUpdate = canAccessPermission("user.update", workspaceId);
  const canDelete = canAccessPermission("user.delete", workspaceId);
  const canMerge = isSuperuser;
  const canOpenProfile = canUpdate || canDelete;
  const isCreateDirty = createDialogOpen && hasUnsavedChanges({ name: createName }, { name: "" });

  const createMutation = useMutation({
    mutationFn: (data: UserCreateInput) => adminService.createUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setCreateDialogOpen(false);
      setCreateName("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setDeletingUser(null);
    },
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({ name: createName });
  };

  const columns: ColumnDef<User>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 60,
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => {
        const user = row.original;
        const initials = user.name
          .split(/[#\s]+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((s) => s[0]?.toUpperCase())
          .join("");
        return (
          <div className="flex items-center gap-2.5">
            <Avatar className="h-7 w-7 text-[11px]">
              <AvatarImage src={user.avatar_url ?? undefined} alt={user.name} />
              <AvatarFallback className="bg-muted/60 text-muted-foreground font-medium">
                {initials || "?"}
              </AvatarFallback>
            </Avatar>
            <span className="font-medium truncate">{user.name}</span>
          </div>
        );
      },
    },
    {
      id: "identities",
      header: "Identities",
      cell: ({ row }) => {
        const user = row.original;
        const discordCount = user.discord?.length || 0;
        const battleTagCount = user.battle_tag?.length || 0;
        const twitchCount = user.twitch?.length || 0;
        const totalCount = discordCount + battleTagCount + twitchCount;

        if (totalCount === 0) {
          return (
            <span className="text-xs text-muted-foreground/50 italic">
              No identities linked
            </span>
          );
        }

        return (
          <TooltipProvider delayDuration={200}>
            <div className="flex items-center gap-1.5">
              {discordCount > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      className="border-[#5865F2]/30 bg-[#5865F2]/10 text-[#5865F2] hover:bg-[#5865F2]/20 gap-1.5 cursor-default"
                      variant="outline"
                    >
                      <Image src="/discord.png" alt="" width={12} height={12} className="h-3 w-3" />
                      {discordCount}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">
                    <p className="font-medium mb-1">Discord ({discordCount})</p>
                    {user.discord.map((d) => (
                      <p key={d.id} className="text-xs opacity-80">{d.name}</p>
                    ))}
                  </TooltipContent>
                </Tooltip>
              )}
              {battleTagCount > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      className="border-[#148EFF]/30 bg-[#148EFF]/10 text-[#148EFF] hover:bg-[#148EFF]/20 gap-1.5 cursor-default"
                      variant="outline"
                    >
                      <Image src="/battlenet.svg" alt="" width={12} height={12} className="h-3 w-3" />
                      {battleTagCount}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">
                    <p className="font-medium mb-1">BattleTag ({battleTagCount})</p>
                    {user.battle_tag.map((bt) => (
                      <p key={bt.id} className="text-xs opacity-80">{bt.battle_tag}</p>
                    ))}
                  </TooltipContent>
                </Tooltip>
              )}
              {twitchCount > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      className="border-[#9146FF]/30 bg-[#9146FF]/10 text-[#9146FF] hover:bg-[#9146FF]/20 gap-1.5 cursor-default"
                      variant="outline"
                    >
                      <Image src="/twitch.png" alt="" width={12} height={12} className="h-3 w-3" />
                      {twitchCount}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">
                    <p className="font-medium mb-1">Twitch ({twitchCount})</p>
                    {user.twitch.map((tw) => (
                      <p key={tw.id} className="text-xs opacity-80">{tw.name}</p>
                    ))}
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
          </TooltipProvider>
        );
      },
    },
    {
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const user = row.original;
        if (!canOpenProfile && !canDelete && !canMerge) {
          return null;
        }
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Open actions for ${user.name}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              {canOpenProfile && (
                <DropdownMenuItem onClick={() => setProfileUser(user)}>
                  <Pencil className="mr-2 h-4 w-4" />
                  Edit Profile
                </DropdownMenuItem>
              )}
              {canMerge && (
                <DropdownMenuItem onClick={() => setMergeUser(user)}>
                  <ArrowRightLeft className="mr-2 h-4 w-4" />
                  Merge
                </DropdownMenuItem>
              )}
              {(canOpenProfile || canMerge) && canDelete && <DropdownMenuSeparator />}
              {canDelete && (
                <DropdownMenuItem onClick={() => setDeletingUser(user)} className="text-destructive">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Player Identities"
        description="Manage tournament identity records and linked Discord, BattleTag, and Twitch handles."
        actions={
          canCreate ? (
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setImportDialogOpen(true)}
              >
                <Upload className="mr-2 h-4 w-4" />
                Import CSV
              </Button>
              <Button
                onClick={() => {
                  createMutation.reset();
                  setCreateName("");
                  setCreateDialogOpen(true);
                }}
              >
                <Plus className="mr-2 h-4 w-4" />
                Create User
              </Button>
            </div>
          ) : null
        }
      />

      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => ["admin", "users", page, search, pageSize, sortField, sortDir]}
        queryFn={(page, search, pageSize, sortField, sortDir) => adminService.getUsers({ page, search, per_page: pageSize, sort: sortField ?? undefined, order: sortDir })}
        columns={columns}
        searchPlaceholder="Search users..."
        emptyMessage="No users found."
        onRowClick={canOpenProfile ? (row) => setProfileUser(row.original) : undefined}
      />

      {/* Create User Dialog */}
      <EntityFormDialog
        open={createDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setCreateName("");
          }
        }}
        title="Create User"
        description="Create a new player identity in the system."
        onSubmit={handleCreateSubmit}
        isSubmitting={createMutation.isPending}
        submittingLabel="Creating player identity…"
        errorMessage={
          createMutation.error instanceof Error
            ? createMutation.error.message
            : undefined
        }
        isDirty={isCreateDirty}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="Player name (e.g. Karnage#22778)"
              required
            />
          </div>
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingUser && (
        <DeleteConfirmDialog
          open={!!deletingUser}
          onOpenChange={(open) => !open && setDeletingUser(null)}
          onConfirm={() => deleteMutation.mutate(deletingUser.id)}
          isDeleting={deleteMutation.isPending}
          title={`Delete ${deletingUser.name}?`}
          cascadeInfo={[
            "All Discord identities",
            "All BattleTag identities",
            "All Twitch identities",
            "All player records",
          ]}
        />
      )}

      {/* Unified Player Profile Dialog */}
      {profileUser && (
        <PlayerProfileDialog
          key={profileUser.id}
          user={profileUser}
          onClose={() => setProfileUser(null)}
          canEdit={canUpdate}
          canDelete={canDelete}
          canMerge={canMerge}
          onMergeRequested={(user) => setMergeUser(user)}
        />
      )}

      {mergeUser && (
        <UserMergeDialog
          key={mergeUser.id}
          sourceUser={mergeUser}
          open={!!mergeUser}
          onOpenChange={(open) => {
            if (!open) setMergeUser(null);
          }}
          onMerged={() => {
            setMergeUser(null);
            if (profileUser?.id === mergeUser.id) {
              setProfileUser(null);
            }
          }}
        />
      )}

      {/* CSV Import Dialog */}
      <CsvImportDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
      />
    </div>
  );
}
