"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowLeft,
  CheckCircle,
  CircleOff,
  ArrowUp,
  Crosshair,
  Eye,
  EyeOff,
  Globe,
  Hash,
  Layers,
  Map,
  Pencil,
  Play,
  Swords,
  Upload,
  Target,
  TestTube,
  Trash2,
  Trophy,
  User,
  UserPlus,
  Users,
  X
} from "lucide-react";

import { ConditionFlowEditor } from "@/components/admin/achievements/ConditionFlowEditor";
import { notifyEvaluationRun } from "@/components/admin/achievements/EvaluationRunSummary";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { TournamentCombobox } from "@/components/admin/TournamentCombobox";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { hasUnsavedChanges } from "@/lib/form-change";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import type {
  AchievementCategory,
  AchievementGrain,
  AchievementRule,
  AchievementRuleUpdateInput,
  AchievementScope
} from "@/types/admin.types";
import {
  ACHIEVEMENT_IMAGE_ACCEPT,
  ACHIEVEMENT_IMAGE_PREVIEW_CLASS,
  MAX_ACHIEVEMENT_IMAGE_BYTES
} from "@/lib/achievement-image";
import { useWorkspaceStore } from "@/stores/workspace.store";

const CATEGORIES: AchievementCategory[] = [
  "overall",
  "hero",
  "division",
  "team",
  "standing",
  "match"
];
const SCOPES: AchievementScope[] = ["global", "tournament", "match"];
const GRAINS: AchievementGrain[] = ["user", "user_tournament", "user_match"];

const CATEGORY_ICONS: Record<string, typeof Globe> = {
  overall: Globe,
  hero: Crosshair,
  division: Layers,
  team: Users,
  standing: Trophy,
  match: Swords
};

const SCOPE_ICONS: Record<string, typeof Globe> = {
  global: Globe,
  tournament: Trophy,
  match: Map
};

const GRAIN_ICONS: Record<string, typeof Globe> = {
  user: User,
  user_tournament: Target,
  user_match: Crosshair
};

function CategoryIcon({ category }: Readonly<{ category: string }>) {
  const Icon = CATEGORY_ICONS[category] ?? Globe;
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

function ScopeIcon({ scope }: Readonly<{ scope: string }>) {
  const Icon = SCOPE_ICONS[scope] ?? Globe;
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

function GrainIcon({ grain }: Readonly<{ grain: string }>) {
  const Icon = GRAIN_ICONS[grain] ?? User;
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

function SortableHead({
  field,
  label,
  currentSort,
  currentOrder,
  onSort
}: Readonly<{
  field: string;
  label: string;
  currentSort: string;
  currentOrder: "asc" | "desc";
  onSort: (field: string) => void;
}>) {
  const isActive = currentSort === field;
  return (
    <TableHead aria-sort={isActive ? (currentOrder === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        className="flex items-center gap-1 hover:text-foreground transition-colors"
        onClick={() => onSort(field)}
      >
        {label}
        {isActive ? (
          currentOrder === "asc" ? (
            <ArrowUp aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <ArrowDown aria-hidden className="h-3.5 w-3.5" />
          )
        ) : (
          <ArrowUp aria-hidden className="h-3.5 w-3.5 opacity-0 group-hover:opacity-30" />
        )}
      </button>
    </TableHead>
  );
}

function buildAchievementFormData(rule: AchievementRule): AchievementRuleUpdateInput {
  return {
    name: rule.name,
    description_ru: rule.description_ru,
    description_en: rule.description_en,
    image_url: rule.image_url,
    hero_id: rule.hero_id,
    category: rule.category,
    scope: rule.scope,
    grain: rule.grain,
    condition_tree: rule.condition_tree,
    depends_on: rule.depends_on,
    enabled: rule.enabled,
    min_tournament_id: rule.min_tournament_id
  };
}

export default function AchievementDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const ruleId = Number(params.id);

  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  // --- State ---
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deletingRule, setDeletingRule] = useState(false);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideUserId, setOverrideUserId] = useState<number | undefined>(undefined);
  const [overrideUserName, setOverrideUserName] = useState("");
  const [overrideAction, setOverrideAction] = useState<"grant" | "revoke">("grant");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideTournamentId, setOverrideTournamentId] = useState<number | undefined>(undefined);
  const [formData, setFormData] = useState<AchievementRuleUpdateInput>({});
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // Condition tree inline editing
  const [editingTree, setEditingTree] = useState(false);
  const [treeData, setTreeData] = useState<Record<string, unknown>>({});

  // Users table state
  const [usersFilterTournamentId, setUsersFilterTournamentId] = useState<number | undefined>(
    undefined
  );
  const [usersSort, setUsersSort] = useState<string>("count");
  const [usersSortOrder, setUsersSortOrder] = useState<"asc" | "desc">("desc");

  // --- Queries ---
  const { data: rule, isLoading } = useQuery({
    queryKey: ["admin", "achievement-rule", workspaceId, ruleId],
    queryFn: () => adminService.getAchievementRule(workspaceId!, ruleId),
    enabled: !!workspaceId
  });

  const { data: tournaments } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null)
  });

  const {
    data: usersData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isError: usersError
  } = useInfiniteQuery({
    queryKey: [
      "admin",
      "achievement-rule-users",
      workspaceId,
      ruleId,
      usersFilterTournamentId,
      usersSort,
      usersSortOrder
    ],
    queryFn: ({ pageParam = 1 }) =>
      adminService.getAchievementRuleUsers(workspaceId!, ruleId, {
        page: pageParam,
        per_page: 30,
        tournament_id: usersFilterTournamentId,
        sort: usersSort,
        order: usersSortOrder
      }),
    getNextPageParam: (lastPage) =>
      lastPage.total / lastPage.per_page > lastPage.page ? lastPage.page + 1 : undefined,
    enabled: !!workspaceId,
    initialPageParam: 1
  });

  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: ["admin", "overrides", workspaceId, ruleId],
    queryFn: async () => {
      const all = await adminService.getAchievementOverrides(workspaceId!);
      return all.filter((o) => o.achievement_rule_id === ruleId);
    },
    enabled: !!workspaceId
  });

  // --- Mutations ---
  const updateMutation = useMutation({
    mutationFn: async (data: AchievementRuleUpdateInput) => {
      const updated = await adminService.updateAchievementRule(workspaceId!, ruleId, data);
      // Upload image if selected
      if (imageFile && updated.slug) {
        const uploadResult = await adminService.uploadAchievementImage(
          updated.slug,
          imageFile,
          workspaceId!
        );
        // Update the rule with the new image URL
        await adminService.updateAchievementRule(workspaceId!, ruleId, {
          image_url: uploadResult.public_url
        });
      }
      return updated;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["admin", "achievement-rule", workspaceId, ruleId]
      });
      queryClient.invalidateQueries({ queryKey: ["admin", "achievements", workspaceId] });
      setEditDialogOpen(false);
      setImageFile(null);
      setImagePreview(null);
    }
  });

  const saveTreeMutation = useMutation({
    mutationFn: (conditionTree: Record<string, unknown>) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { condition_tree: conditionTree }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["admin", "achievement-rule", workspaceId, ruleId]
      });
      queryClient.invalidateQueries({ queryKey: ["admin", "achievements", workspaceId] });
      setEditingTree(false);
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteAchievementRule(workspaceId!, ruleId),
    onSuccess: () => router.push("/admin/achievements")
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { enabled }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["admin", "achievement-rule", workspaceId, ruleId]
      })
  });

  const evaluateMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.evaluateAchievements(workspaceId!, {
        tournament_id: tournamentId,
        rule_ids: [ruleId]
      }),
    onSuccess: (data) => {
      notifyEvaluationRun(data);
      queryClient.invalidateQueries({
        queryKey: ["admin", "achievement-rule-users", workspaceId, ruleId]
      });
    }
  });

  const testMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.testAchievementRule(workspaceId!, ruleId, tournamentId),
    onSuccess: (data) => {
      notify.success("Dry-run complete", {
        description: `${data.qualifying_count} users qualify`
      });
    }
  });

  const overrideMutation = useMutation({
    mutationFn: () =>
      adminService.createAchievementOverride(workspaceId!, {
        achievement_rule_id: ruleId,
        user_id: overrideUserId!,
        tournament_id: overrideTournamentId ?? null,
        action: overrideAction,
        reason: overrideReason
      }),
    onSuccess: () => {
      refetchOverrides();
      setOverrideDialogOpen(false);
      setOverrideUserId(undefined);
      setOverrideUserName("");
      setOverrideReason("");
    }
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementOverride(workspaceId!, id),
    onSuccess: () => refetchOverrides()
  });

  // --- Helpers ---
  const openEditDialog = () => {
    if (!rule) return;
    setFormData(buildAchievementFormData(rule));
    updateMutation.reset();
    setEditDialogOpen(true);
  };

  const formInitial = rule
    ? buildAchievementFormData(rule)
    : {};
  const isFormDirty = editDialogOpen && hasUnsavedChanges(formData, formInitial);

  const totalUsers = usersData?.pages[0]?.total ?? 0;

  const handleUsersSort = (field: string) => {
    if (usersSort === field) {
      setUsersSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setUsersSort(field);
      setUsersSortOrder("desc");
    }
  };

  if (!workspaceId) {
    return <div className="p-6 text-muted-foreground">Select a workspace first.</div>;
  }

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (!rule) {
    return <div className="p-6 text-muted-foreground">Achievement not found.</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Back to achievements">
          <Link href="/admin/achievements">
            <ArrowLeft aria-hidden className="h-4 w-4" />
          </Link>
        </Button>
        {rule.image_url && (
          <img
            src={rule.image_url}
            alt={rule.name}
            className="h-12 w-12 rounded-lg object-cover border"
          />
        )}
        <div className="min-w-0 flex-1">
          <AdminPageHeader
            title={rule.name}
            description={rule.slug}
            meta={
              rule.enabled ? (
                <StatusIcon icon={CheckCircle} label="Enabled" variant="success" />
              ) : (
                <StatusIcon icon={CircleOff} label="Disabled" variant="muted" />
              )
            }
            actions={
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => testMutation.mutate(undefined)}
                >
                  <TestTube aria-hidden className="mr-2 h-4 w-4" />
                  Test conditions
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => evaluateMutation.mutate(undefined)}
                >
                  <Play
                    aria-hidden
                    className={`mr-2 h-4 w-4 ${evaluateMutation.isPending ? "animate-spin" : ""}`}
                  />
                  {evaluateMutation.isPending ? "Evaluating…" : "Run evaluation"}
                </Button>
                {canUpdate && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleMutation.mutate(!rule.enabled)}
                  >
                    {rule.enabled ? (
                      <EyeOff aria-hidden className="mr-2 h-4 w-4" />
                    ) : (
                      <Eye aria-hidden className="mr-2 h-4 w-4" />
                    )}
                    {rule.enabled ? "Disable achievement" : "Enable achievement"}
                  </Button>
                )}
                {canUpdate && (
                  <Button size="sm" onClick={openEditDialog}>
                    <Pencil aria-hidden className="mr-2 h-4 w-4" />
                    Edit achievement
                  </Button>
                )}
                {canDelete && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDeletingRule(true)}
                  >
                    <Trash2 aria-hidden className="mr-2 h-4 w-4" />
                    Delete achievement
                  </Button>
                )}
              </>
            }
          />
        </div>
      </div>

      {/* Info */}
      <div className="grid grid-cols-1 gap-6">
        {/* Meta card */}
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-3 gap-2">
              <div className="flex items-center gap-2">
                <CategoryIcon category={rule.category} />
                <div>
                  <p className="text-muted-foreground text-xs">Category</p>
                  <p className="capitalize">{rule.category}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <ScopeIcon scope={rule.scope} />
                <div>
                  <p className="text-muted-foreground text-xs">Scope</p>
                  <p className="capitalize">{rule.scope}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <GrainIcon grain={rule.grain} />
                <div>
                  <p className="text-muted-foreground text-xs">Grain</p>
                  <p>{rule.grain.replace("_", " + ")}</p>
                </div>
              </div>
            </div>
            <Separator />
            <div>
              <p className="text-muted-foreground text-xs">Description (RU)</p>
              <p>{rule.description_ru}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Description (EN)</p>
              <p>{rule.description_en}</p>
            </div>
            <Separator />
            <div className="grid grid-cols-3 gap-2">
              <div className="flex items-center gap-2">
                <Hash className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-muted-foreground text-xs">Version</p>
                  <p>{rule.rule_version}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Trophy className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-muted-foreground text-xs">Min Tournament</p>
                  <p>{rule.min_tournament_id ?? "-"}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-muted-foreground text-xs">Users Earned</p>
                  <p className="font-medium">{totalUsers}</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Condition tree — full width, inline editable */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Condition Tree</CardTitle>
            <CardDescription>
              {editingTree
                ? "Edit the evaluation logic"
                : "Visual representation of the evaluation logic"}
            </CardDescription>
          </div>
          {canUpdate && !editingTree && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setTreeData(rule.condition_tree as Record<string, unknown>);
                setEditingTree(true);
              }}
            >
              <Pencil className="mr-2 h-4 w-4" />
              Edit Tree
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {editingTree ? (
            <div className="space-y-4">
              <ConditionFlowEditor value={treeData} onChange={setTreeData} />
              <div className="flex items-center justify-end gap-2 pt-2 border-t">
                {saveTreeMutation.error instanceof Error && (
                  <p className="text-sm text-destructive mr-auto">
                    {saveTreeMutation.error.message}
                  </p>
                )}
                <Button
                  variant="outline"
                  onClick={() => setEditingTree(false)}
                  disabled={saveTreeMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => saveTreeMutation.mutate(treeData)}
                  disabled={saveTreeMutation.isPending}
                >
                  {saveTreeMutation.isPending ? "Saving…" : "Save condition tree"}
                </Button>
              </div>
            </div>
          ) : (
            <ConditionFlowEditor value={rule.condition_tree as Record<string, unknown>} readOnly />
          )}
        </CardContent>
      </Card>

      {/* Users who earned this achievement */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Users ({totalUsers})</CardTitle>
            <CardDescription>Players who earned this achievement</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-64">
              <TournamentCombobox
                tournaments={tournaments?.results ?? []}
                value={usersFilterTournamentId}
                onSelect={(t) => setUsersFilterTournamentId(t?.id)}
                placeholder="All tournaments"
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                overrideMutation.reset();
                setOverrideDialogOpen(true);
              }}
            >
              <UserPlus className="mr-2 h-4 w-4" />
              Manual Override
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead
                  field="user_name"
                  label="User"
                  currentSort={usersSort}
                  currentOrder={usersSortOrder}
                  onSort={handleUsersSort}
                />
                <SortableHead
                  field="count"
                  label="Count"
                  currentSort={usersSort}
                  currentOrder={usersSortOrder}
                  onSort={handleUsersSort}
                />
                <SortableHead
                  field="last_tournament_id"
                  label="Last Tournament"
                  currentSort={usersSort}
                  currentOrder={usersSortOrder}
                  onSort={handleUsersSort}
                />
                <SortableHead
                  field="first_qualified"
                  label="First Earned"
                  currentSort={usersSort}
                  currentOrder={usersSortOrder}
                  onSort={handleUsersSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {usersData?.pages.map((page) =>
                page.results.map((row) => (
                  <TableRow key={row.user_id}>
                    <TableCell>
                      <Link href={`/users/${row.user_id}`} className="text-primary hover:underline">
                        {row.user_name}
                      </Link>
                    </TableCell>
                    <TableCell>{row.count}</TableCell>
                    <TableCell>
                      {row.last_tournament_id ? (
                        <Link
                          href={`/tournaments/${row.last_tournament_id}`}
                          className="text-primary hover:underline"
                        >
                          #{row.last_tournament_id}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.first_qualified
                        ? new Date(row.first_qualified).toLocaleDateString()
                        : "-"}
                    </TableCell>
                  </TableRow>
                ))
              )}
              {totalUsers === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                    No users have earned this achievement yet
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {totalUsers > 0 ? (
            <InfiniteScrollFooter
              className="mt-4"
              loaded={usersData?.pages.reduce((count, page) => count + page.results.length, 0) ?? 0}
              total={totalUsers}
              unit="users"
              hasNextPage={hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              fetchNextPage={fetchNextPage}
              isError={usersError}
            />
          ) : null}
        </CardContent>
      </Card>

      {/* Overrides for this achievement */}
      {overrides && overrides.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Overrides</CardTitle>
            <CardDescription>Manual grants and revocations</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User ID</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Tournament</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {overrides.map((ov) => (
                  <TableRow key={ov.id}>
                    <TableCell>#{ov.user_id}</TableCell>
                    <TableCell>
                      <Badge variant={ov.action === "grant" ? "success" : "destructive"}>
                        {ov.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
                    <TableCell>{ov.tournament_id ?? "-"}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(ov.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${ov.action} override`}
                        onClick={() => deleteOverrideMutation.mutate(ov.id)}
                      >
                        <Trash2 aria-hidden className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* ─── Override Dialog ──────────────────────────────────────────── */}
      <Dialog open={overrideDialogOpen} onOpenChange={setOverrideDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manual Override: {rule.name}</DialogTitle>
            <DialogDescription>Grant or revoke this achievement for a user</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>User</Label>
              <UserSearchCombobox
                value={overrideUserId}
                selectedName={overrideUserName}
                onSelect={(user) => {
                  setOverrideUserId(user?.id);
                  setOverrideUserName(user?.name ?? "");
                }}
                allowClear
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Action</Label>
                <Select
                  value={overrideAction}
                  onValueChange={(v) => setOverrideAction(v as "grant" | "revoke")}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="grant">Grant</SelectItem>
                    <SelectItem value="revoke">Revoke</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Tournament (optional)</Label>
                <TournamentCombobox
                  tournaments={tournaments?.results ?? []}
                  value={overrideTournamentId}
                  onSelect={(t) => setOverrideTournamentId(t?.id)}
                  placeholder="None"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Reason</Label>
              <Textarea
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Why is this being granted/revoked?"
                required
              />
            </div>
            {overrideMutation.error instanceof Error && (
              <p className="text-sm text-destructive">{overrideMutation.error.message}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOverrideDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => overrideMutation.mutate()}
              disabled={!overrideUserId || !overrideReason || overrideMutation.isPending}
            >
              {overrideMutation.isPending
                ? "Saving…"
                : overrideAction === "grant"
                  ? "Grant"
                  : "Revoke"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Edit Dialog ─────────────────────────────────────────────── */}
      <EntityFormDialog
        open={editDialogOpen}
        onOpenChange={(open) => {
          if (!open) setEditDialogOpen(false);
        }}
        title={`Edit: ${rule.slug}`}
        description="Update achievement metadata"
        onSubmit={(e) => {
          e.preventDefault();
          updateMutation.mutate(formData);
        }}
        isSubmitting={updateMutation.isPending}
        submittingLabel="Updating…"
        errorMessage={
          updateMutation.error instanceof Error ? updateMutation.error.message : undefined
        }
        isDirty={isFormDirty}
      >
        <ScrollArea className="max-h-[60vh]">
          <div className="space-y-4 pr-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={formData.name ?? ""}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>

            {/* Image upload */}
            <div className="space-y-2">
              <Label>Image</Label>
              <div className="flex items-center gap-4">
                {(imagePreview || formData.image_url) && (
                  <img
                    src={imagePreview ?? formData.image_url ?? ""}
                    alt="Achievement"
                    className={ACHIEVEMENT_IMAGE_PREVIEW_CLASS}
                  />
                )}
                <div className="flex flex-col gap-2">
                  <input
                    ref={imageInputRef}
                    type="file"
                    accept={ACHIEVEMENT_IMAGE_ACCEPT}
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (file.size > MAX_ACHIEVEMENT_IMAGE_BYTES) {
                        alert("File too large (max 5 MB)");
                        return;
                      }
                      setImageFile(file);
                      setImagePreview(URL.createObjectURL(file));
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => imageInputRef.current?.click()}
                  >
                    <Upload className="mr-2 h-4 w-4" />
                    {formData.image_url || imagePreview ? "Change Image" : "Upload Image"}
                  </Button>
                  {(imagePreview || formData.image_url) && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setImageFile(null);
                        setImagePreview(null);
                        setFormData({ ...formData, image_url: null });
                      }}
                    >
                      <X className="mr-2 h-4 w-4" />
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Description (RU)</Label>
                <Textarea
                  value={formData.description_ru ?? ""}
                  onChange={(e) => setFormData({ ...formData, description_ru: e.target.value })}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>Description (EN)</Label>
                <Textarea
                  value={formData.description_en ?? ""}
                  onChange={(e) => setFormData({ ...formData, description_en: e.target.value })}
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Category</Label>
                <Select
                  value={formData.category ?? "overall"}
                  onValueChange={(v) =>
                    setFormData({ ...formData, category: v as AchievementCategory })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Scope</Label>
                <Select
                  value={formData.scope ?? "global"}
                  onValueChange={(v) => setFormData({ ...formData, scope: v as AchievementScope })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCOPES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Grain</Label>
                <Select
                  value={formData.grain ?? "user"}
                  onValueChange={(v) => setFormData({ ...formData, grain: v as AchievementGrain })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {GRAINS.map((g) => (
                      <SelectItem key={g} value={g}>
                        {g}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </ScrollArea>
      </EntityFormDialog>

      {/* Delete dialog */}
      <ConfirmDialog
        open={deletingRule}
        onOpenChange={setDeletingRule}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: `Delete achievement "${rule.slug}"`,
          description:
            "The record and its linked data are removed permanently. This cannot be undone.",
          confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
          tone: "danger",
          cascade: ["Every evaluation result and manual override for this achievement"],
        }}
      />
    </div>
  );
}
