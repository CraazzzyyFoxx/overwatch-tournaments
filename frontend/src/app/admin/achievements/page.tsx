"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import {
  MoreHorizontal,
  Plus,
  Pencil,
  Trash2,
  Play,
  TestTube,
  Sprout,
  RotateCcw,
  Eye,
  EyeOff,
  Upload,
  Download,
  LibraryBig,
  UserPlus,
  X,
  Globe,
  Crosshair,
  Layers,
  Users,
  Trophy,
  Swords,
  Map,
  User,
  Target,
  type LucideIcon,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { AchievementCombobox } from "@/components/admin/achievements/AchievementCombobox";
import { TournamentCombobox } from "@/components/admin/TournamentCombobox";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import type {
  AchievementRule,
  AchievementRuleExportEnvelope,
  AchievementRuleImportResult,
  AchievementRuleCreateInput,
  AchievementRuleUpdateInput,
  AchievementCategory,
  AchievementScope,
  AchievementGrain,
  AchievementOverrideRead,
  EvaluationRunRead,
} from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useWorkspaceStore } from "@/stores/workspace.store";

const CATEGORIES: AchievementCategory[] = ["overall", "hero", "division", "team", "standing", "match"];
const SCOPES: AchievementScope[] = ["global", "tournament", "match"];
const GRAINS: AchievementGrain[] = ["user", "user_tournament", "user_match"];

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  overall: Globe, hero: Crosshair, division: Layers,
  team: Users, standing: Trophy, match: Swords,
};
const SCOPE_ICONS: Record<string, LucideIcon> = {
  global: Globe, tournament: Trophy, match: Map,
};
const GRAIN_ICONS: Record<string, LucideIcon> = {
  user: User, user_tournament: Target, user_match: Crosshair,
};

function IconLabel({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="capitalize">{label}</span>
    </span>
  );
}

function countLeafConditions(node: Record<string, unknown>): number {
  if (node.AND) return (node.AND as Record<string, unknown>[]).reduce((s, c) => s + countLeafConditions(c), 0);
  if (node.OR) return (node.OR as Record<string, unknown>[]).reduce((s, c) => s + countLeafConditions(c), 0);
  if (node.NOT) return countLeafConditions(node.NOT as Record<string, unknown>);
  return 1;
}

const emptyForm: AchievementRuleCreateInput = {
  slug: "",
  name: "",
  description_ru: "",
  description_en: "",
  category: "overall",
  scope: "global",
  grain: "user",
  condition_tree: {},
  depends_on: [],
  enabled: true,
};

function getFormData(rule: AchievementRule): AchievementRuleUpdateInput {
  return {
    slug: rule.slug,
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
    min_tournament_id: rule.min_tournament_id,
  };
}

export default function AchievementsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  // CRUD state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AchievementRule | null>(null);
  const [deletingRule, setDeletingRule] = useState<AchievementRule | null>(null);
  const [testResult, setTestResult] = useState<{ slug: string; count: number; sample: number[][] } | null>(null);
  const [formData, setFormData] = useState<AchievementRuleCreateInput | AchievementRuleUpdateInput>({ ...emptyForm });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const jsonImportInputRef = useRef<HTMLInputElement>(null);
  const [importResult, setImportResult] = useState<AchievementRuleImportResult | null>(null);
  const [libraryDialogOpen, setLibraryDialogOpen] = useState(false);
  const [librarySourceWorkspaceId, setLibrarySourceWorkspaceId] = useState<number | undefined>(undefined);
  const [librarySelectedSlugs, setLibrarySelectedSlugs] = useState<Set<string>>(new Set());

  // Evaluate dialog state
  const [evaluateDialogOpen, setEvaluateDialogOpen] = useState(false);
  const [evalTournamentId, setEvalTournamentId] = useState<number | undefined>(undefined);
  const [evalSelectedRuleIds, setEvalSelectedRuleIds] = useState<Set<number>>(new Set());
  const [evaluationResult, setEvaluationResult] = useState<EvaluationRunRead | null>(null);

  // Override dialog state
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideUserId, setOverrideUserId] = useState<number | undefined>(undefined);
  const [overrideUserName, setOverrideUserName] = useState<string>("");
  const [overrideRuleId, setOverrideRuleId] = useState<number | undefined>(undefined);
  const [overrideAction, setOverrideAction] = useState<"grant" | "revoke">("grant");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideTournamentId, setOverrideTournamentId] = useState<number | undefined>(undefined);

  const canCreate = canAccessPermission("achievement.create", workspaceId);
  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const cacheKey = ["admin", "achievements", workspaceId];

  // --- Queries ---

  const { data: tournaments } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
  });

  const { data: allRules } = useQuery({
    queryKey: cacheKey,
    queryFn: () => adminService.getAchievementRules(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: ["admin", "overrides", workspaceId],
    queryFn: () => adminService.getAchievementOverrides(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: libraryWorkspaces } = useQuery({
    queryKey: ["admin", "achievement-library-workspaces", workspaceId],
    queryFn: () => adminService.getAchievementLibraryWorkspaces(workspaceId!),
    enabled: !!workspaceId && libraryDialogOpen,
  });

  const { data: libraryRules } = useQuery({
    queryKey: ["admin", "achievement-library-rules", workspaceId, librarySourceWorkspaceId],
    queryFn: () => adminService.getAchievementLibraryRules(workspaceId!, librarySourceWorkspaceId!),
    enabled: !!workspaceId && libraryDialogOpen && !!librarySourceWorkspaceId,
  });

  // --- Mutations ---

  const createMutation = useMutation({
    mutationFn: async (data: AchievementRuleCreateInput) => {
      const created = await adminService.createAchievementRule(workspaceId!, data);
      if (imageFile && created.slug) {
        const uploadResult = await adminService.uploadAchievementImage(created.slug, imageFile, workspaceId!);
        await adminService.updateAchievementRule(workspaceId!, created.id, {
          image_url: uploadResult.public_url,
        });
      }
      return created;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      setCreateDialogOpen(false);
      setFormData({ ...emptyForm });
      setImageFile(null);
      setImagePreview(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AchievementRuleUpdateInput }) =>
      adminService.updateAchievementRule(workspaceId!, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      setEditingRule(null);
      setFormData({ ...emptyForm });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementRule(workspaceId!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      setDeletingRule(null);
    },
  });

  const seedMutation = useMutation({
    mutationFn: () => adminService.seedAchievementRules(workspaceId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cacheKey }),
  });

  const hardResetMutation = useMutation({
    mutationFn: () => adminService.hardResetAchievementRules(workspaceId!),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      queryClient.invalidateQueries({ queryKey: ["admin", "overrides", workspaceId] });
      setEvaluationResult(data.run);
    },
  });

  const importMutation = useMutation({
    mutationFn: (data: AchievementRuleExportEnvelope) =>
      adminService.importAchievementRules(workspaceId!, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      setImportResult(data);
      if (jsonImportInputRef.current) {
        jsonImportInputRef.current.value = "";
      }
    },
  });

  const libraryImportMutation = useMutation({
    mutationFn: (data: { source_workspace_id: number; slugs: string[] }) =>
      adminService.importAchievementLibraryRules(workspaceId!, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: cacheKey });
      setImportResult(data);
      setLibraryDialogOpen(false);
      setLibrarySelectedSlugs(new Set());
    },
  });

  const evaluateMutation = useMutation({
    mutationFn: (params: { tournament_id?: number; rule_ids?: number[] }) =>
      adminService.evaluateAchievements(workspaceId!, params),
    onSuccess: (data) => {
      setEvaluationResult(data);
      setEvaluateDialogOpen(false);
    },
  });

  const testMutation = useMutation({
    mutationFn: (ruleId: number) => adminService.testAchievementRule(workspaceId!, ruleId),
    onSuccess: (data) =>
      setTestResult({ slug: data.rule_slug, count: data.qualifying_count, sample: data.sample }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      adminService.updateAchievementRule(workspaceId!, id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cacheKey }),
  });

  const overrideMutation = useMutation({
    mutationFn: () =>
      adminService.createAchievementOverride(workspaceId!, {
        achievement_rule_id: overrideRuleId!,
        user_id: overrideUserId!,
        tournament_id: overrideTournamentId ?? null,
        action: overrideAction,
        reason: overrideReason,
      }),
    onSuccess: () => {
      refetchOverrides();
      setOverrideDialogOpen(false);
      setOverrideUserId(undefined);
      setOverrideUserName("");
      setOverrideRuleId(undefined);
      setOverrideReason("");
      setOverrideTournamentId(undefined);
    },
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementOverride(workspaceId!, id),
    onSuccess: () => refetchOverrides(),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingRule) {
      updateMutation.mutate({ id: editingRule.id, data: formData as AchievementRuleUpdateInput });
    } else {
      createMutation.mutate(formData as AchievementRuleCreateInput);
    }
  };

  const handleEvaluate = () => {
    const ruleIds = evalSelectedRuleIds.size > 0 ? Array.from(evalSelectedRuleIds) : undefined;
    evaluateMutation.mutate({
      tournament_id: evalTournamentId,
      rule_ids: ruleIds,
    });
  };

  const handleExport = async () => {
    const { blob, filename } = await adminService.exportAchievementRules(workspaceId!);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  };

  const handleJsonImportFile = async (file: File | null) => {
    if (!file) return;
    const text = await file.text();
    let parsed: AchievementRuleExportEnvelope;
    try {
      parsed = JSON.parse(text) as AchievementRuleExportEnvelope;
    } catch {
      window.alert("Invalid JSON file");
      if (jsonImportInputRef.current) {
        jsonImportInputRef.current.value = "";
      }
      return;
    }
    importMutation.mutate(parsed);
  };

  const toggleLibrarySlug = (slug: string, checked: boolean) => {
    setLibrarySelectedSlugs((prev) => {
      const next = new Set(prev);
      if (checked) next.add(slug);
      else next.delete(slug);
      return next;
    });
  };

  const handleLibraryImport = () => {
    if (!librarySourceWorkspaceId || librarySelectedSlugs.size === 0) return;
    libraryImportMutation.mutate({
      source_workspace_id: librarySourceWorkspaceId,
      slugs: Array.from(librarySelectedSlugs),
    });
  };

  const formInitial = editingRule ? getFormData(editingRule) : emptyForm;
  const isFormDirty = (createDialogOpen || !!editingRule) && hasUnsavedChanges(formData, formInitial);

  // --- Evaluate dialog helpers ---

  const rulesByCategory = (allRules ?? []).reduce<Record<string, AchievementRule[]>>((acc, rule) => {
    (acc[rule.category] ??= []).push(rule);
    return acc;
  }, {});

  const allLibrarySlugs = (libraryRules ?? []).map((rule) => rule.slug);
  const allLibrarySelected =
    allLibrarySlugs.length > 0 && allLibrarySlugs.every((slug) => librarySelectedSlugs.has(slug));

  const toggleCategory = (category: string, checked: boolean) => {
    const ids = (rulesByCategory[category] ?? []).map((r) => r.id);
    setEvalSelectedRuleIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => (checked ? next.add(id) : next.delete(id)));
      return next;
    });
  };

  const toggleRule = (ruleId: number, checked: boolean) => {
    setEvalSelectedRuleIds((prev) => {
      const next = new Set(prev);
      checked ? next.add(ruleId) : next.delete(ruleId);
      return next;
    });
  };

  // --- Columns ---

  const columns: ColumnDef<AchievementRule>[] = [
    { accessorKey: "id", header: "ID", size: 60 },
    {
      accessorKey: "enabled",
      header: "Status",
      size: 80,
      cell: ({ row }) => (
        <Badge variant={row.original.enabled ? "default" : "secondary"}>
          {row.original.enabled ? "On" : "Off"}
        </Badge>
      ),
    },
    { accessorKey: "slug", header: "Slug", size: 180 },
    { accessorKey: "name", header: "Name" },
    {
      accessorKey: "category",
      header: "Category",
      size: 120,
      cell: ({ row }) => (
        <IconLabel icon={CATEGORY_ICONS[row.original.category] ?? Globe} label={row.original.category} />
      ),
    },
    {
      accessorKey: "scope",
      header: "Scope",
      size: 120,
      cell: ({ row }) => (
        <IconLabel icon={SCOPE_ICONS[row.original.scope] ?? Globe} label={row.original.scope} />
      ),
    },
    {
      accessorKey: "grain",
      header: "Grain",
      size: 140,
      cell: ({ row }) => (
        <IconLabel icon={GRAIN_ICONS[row.original.grain] ?? User} label={row.original.grain.replace("_", " + ")} />
      ),
    },
    { accessorKey: "rule_version", header: "Ver", size: 50 },
    {
      id: "conditions_count",
      header: "Rules",
      size: 70,
      accessorFn: (row) => countLeafConditions(row.condition_tree),
      cell: ({ getValue }) => <span className="tabular-nums">{getValue<number>()}</span>,
    },
    {
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const rule = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Actions for ${rule.slug}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => router.push(`/admin/achievements/${rule.id}`)}>
                <Eye className="mr-2 h-4 w-4" />
                View
              </DropdownMenuItem>
              {canUpdate && (
                <DropdownMenuItem
                  onClick={() => {
                    updateMutation.reset();
                    setEditingRule(rule);
                    setFormData(getFormData(rule));
                  }}
                >
                  <Pencil className="mr-2 h-4 w-4" />
                  Edit
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => testMutation.mutate(rule.id)}>
                <TestTube className="mr-2 h-4 w-4" />
                Test (dry-run)
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  setEvalSelectedRuleIds(new Set([rule.id]));
                  setEvalTournamentId(undefined);
                  setEvaluateDialogOpen(true);
                }}
              >
                <Play className="mr-2 h-4 w-4" />
                Evaluate this
              </DropdownMenuItem>
              {canUpdate && (
                <DropdownMenuItem
                  onClick={() => toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled })}
                >
                  {rule.enabled ? (
                    <><EyeOff className="mr-2 h-4 w-4" />Disable</>
                  ) : (
                    <><Eye className="mr-2 h-4 w-4" />Enable</>
                  )}
                </DropdownMenuItem>
              )}
              {canUpdate && canDelete && <DropdownMenuSeparator />}
              {canDelete && (
                <DropdownMenuItem onClick={() => setDeletingRule(rule)} className="text-destructive">
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

  if (!workspaceId) {
    return <div className="p-6 text-muted-foreground">Select a workspace first.</div>;
  }

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Achievements"
        description="Manage achievements with condition tree evaluation engine"
        actions={
          <div className="flex gap-2">
            <input
              ref={jsonImportInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => void handleJsonImportFile(e.target.files?.[0] ?? null)}
            />
            <Button variant="outline" onClick={() => void handleExport()}>
              <Download className="mr-2 h-4 w-4" />
              Export JSON
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setLibraryDialogOpen(true);
                setLibrarySelectedSlugs(new Set());
              }}
            >
              <LibraryBig className="mr-2 h-4 w-4" />
              Library
            </Button>
            {(canCreate || canUpdate) && (
              <Button
                variant="outline"
                onClick={() => jsonImportInputRef.current?.click()}
                disabled={importMutation.isPending}
              >
                <Upload className={`mr-2 h-4 w-4 ${importMutation.isPending ? "animate-spin" : ""}`} />
                Import JSON
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => {
                setEvalSelectedRuleIds(new Set());
                setEvalTournamentId(undefined);
                setEvaluateDialogOpen(true);
              }}
            >
              <Play className="mr-2 h-4 w-4" />
              Evaluate
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                overrideMutation.reset();
                setOverrideDialogOpen(true);
              }}
            >
              <UserPlus className="mr-2 h-4 w-4" />
              Manual Override
            </Button>
            {canCreate && (
              <Button
                variant="outline"
                onClick={() => seedMutation.mutate()}
                disabled={seedMutation.isPending}
              >
                <Sprout className={`mr-2 h-4 w-4 ${seedMutation.isPending ? "animate-spin" : ""}`} />
                Seed Defaults
              </Button>
            )}
            {canCreate && (
              <Button
                variant="destructive"
                onClick={() => {
                  if (!window.confirm("Hard reset achievements for this workspace? This will replace the rule catalog, clear current results, and run a full reevaluation.")) {
                    return;
                  }
                  hardResetMutation.mutate();
                }}
                disabled={hardResetMutation.isPending}
              >
                <RotateCcw className={`mr-2 h-4 w-4 ${hardResetMutation.isPending ? "animate-spin" : ""}`} />
                Hard Reset
              </Button>
            )}
            {canCreate && (
              <Button
                onClick={() => {
                  createMutation.reset();
                  updateMutation.reset();
                  setFormData({ ...emptyForm });
                  setCreateDialogOpen(true);
                }}
              >
                <Plus className="mr-2 h-4 w-4" />
                Create Achievement
              </Button>
            )}
          </div>
        }
      />

      {/* Evaluation result banner */}
      {evaluationResult && (
        <div className="rounded-lg border p-4 bg-muted/50 space-y-1">
          <div className="flex items-center justify-between">
            <p className="font-medium">
              Evaluation Run: <Badge variant={evaluationResult.status === "done" ? "default" : "destructive"}>{evaluationResult.status}</Badge>
              {evaluationResult.tournament_id && (
                <span className="ml-2 text-sm text-muted-foreground">
                  (Tournament #{evaluationResult.tournament_id})
                </span>
              )}
            </p>
            <Button variant="ghost" size="icon" onClick={() => setEvaluationResult(null)}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            Evaluated: {evaluationResult.rules_evaluated} |
            Created: +{evaluationResult.results_created} |
            Removed: -{evaluationResult.results_removed}
            {evaluationResult.error_message && (
              <span className="text-destructive ml-2">{evaluationResult.error_message}</span>
            )}
          </p>
        </div>
      )}

      {importResult && (
        <div className="rounded-lg border p-4 bg-muted/50 space-y-3">
          <div className="flex items-center justify-between">
            <p className="font-medium">
              Import Result
              <span className="ml-2 text-sm text-muted-foreground">
                Created: +{importResult.created} | Updated: {importResult.updated}
              </span>
            </p>
            <Button variant="ghost" size="icon" onClick={() => setImportResult(null)}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          {importResult.warnings.length > 0 && (
            <ScrollArea className="h-28 rounded border bg-background px-3 py-2">
              <div className="space-y-1 text-sm">
                {importResult.warnings.map((warning, index) => (
                  <p key={`${warning.slug}-${index}`}>
                    <span className="font-medium">{warning.slug}:</span> {warning.message}
                  </p>
                ))}
              </div>
            </ScrollArea>
          )}
        </div>
      )}

      {/* Achievements table */}
      <AdminDataTable
        queryKey={(page, search, pageSize, sf, sd) => [...cacheKey, page, search, pageSize, sf, sd]}
        queryFn={async (page, search, pageSize, sortField, sortDir) => {
          const rules = await adminService.getAchievementRules(workspaceId!);
          const filtered = search
            ? rules.filter(
                (r) =>
                  r.slug.toLowerCase().includes(search.toLowerCase()) ||
                  r.name.toLowerCase().includes(search.toLowerCase()),
              )
            : rules;
          const sorted = sortField
            ? [...filtered].sort((a, b) => {
                const va = sortField === "conditions_count"
                  ? countLeafConditions(a.condition_tree)
                  : (a as unknown as Record<string, unknown>)[sortField];
                const vb = sortField === "conditions_count"
                  ? countLeafConditions(b.condition_tree)
                  : (b as unknown as Record<string, unknown>)[sortField];
                const cmp = typeof va === "number" && typeof vb === "number"
                  ? va - vb
                  : String(va ?? "").localeCompare(String(vb ?? ""));
                return sortDir === "desc" ? -cmp : cmp;
              })
            : filtered;
          const start = (page - 1) * pageSize;
          return {
            page,
            per_page: pageSize,
            total: sorted.length,
            results: sorted.slice(start, start + pageSize),
          };
        }}
        columns={columns}
        searchPlaceholder="Search achievements..."
        emptyMessage="No achievements found. Click 'Seed Defaults' to create the standard set."
        onRowClick={(row) => {
          router.push(`/admin/achievements/${row.original.id}`);
        }}
      />

      {/* Overrides table */}
      {overrides && overrides.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Manual Overrides</CardTitle>
            <CardDescription>Manually granted or revoked achievements</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Achievement</TableHead>
                  <TableHead>User ID</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Tournament</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {overrides.map((ov) => (
                  <TableRow key={ov.id}>
                    <TableCell>
                      {allRules?.find((r) => r.id === ov.achievement_rule_id)?.slug ?? ov.achievement_rule_id}
                    </TableCell>
                    <TableCell>{ov.user_id}</TableCell>
                    <TableCell>
                      <Badge variant={ov.action === "grant" ? "default" : "destructive"}>
                        {ov.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
                    <TableCell>{ov.tournament_id ?? "-"}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => deleteOverrideMutation.mutate(ov.id)}
                        disabled={deleteOverrideMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* ─── Evaluate Dialog ──────────────────────────────────────────────── */}
      <Dialog
        open={libraryDialogOpen}
        onOpenChange={(open) => {
          setLibraryDialogOpen(open);
          if (!open) {
            setLibrarySelectedSlugs(new Set());
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Achievement Library</DialogTitle>
            <DialogDescription>
              Import achievements from another workspace into the current workspace.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Source workspace</Label>
              <Select
                value={librarySourceWorkspaceId ? String(librarySourceWorkspaceId) : ""}
                onValueChange={(value) => {
                  setLibrarySourceWorkspaceId(value ? Number(value) : undefined);
                  setLibrarySelectedSlugs(new Set());
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select workspace" />
                </SelectTrigger>
                <SelectContent>
                  {(libraryWorkspaces ?? []).map((workspace) => (
                    <SelectItem key={workspace.id} value={String(workspace.id)}>
                      {workspace.name} ({workspace.rules_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>
                  Achievements ({librarySelectedSlugs.size > 0 ? `${librarySelectedSlugs.size} selected` : "none selected"})
                </Label>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setLibrarySelectedSlugs(new Set(allLibrarySlugs))}
                    disabled={allLibrarySlugs.length === 0 || allLibrarySelected}
                  >
                    Select all
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setLibrarySelectedSlugs(new Set())}
                    disabled={librarySelectedSlugs.size === 0}
                  >
                    Clear
                  </Button>
                </div>
              </div>
              <ScrollArea className="h-[40vh] rounded border p-3">
                {!librarySourceWorkspaceId && (
                  <p className="text-sm text-muted-foreground">Select a source workspace to load achievements.</p>
                )}
                {librarySourceWorkspaceId && (libraryRules?.length ?? 0) === 0 && (
                  <p className="text-sm text-muted-foreground">No achievements found in the selected workspace.</p>
                )}
                <div className="space-y-2">
                  {(libraryRules ?? []).map((rule) => (
                    <label
                      key={rule.slug}
                      className="flex items-center justify-between gap-3 rounded border px-3 py-2 text-sm"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <Checkbox
                          checked={librarySelectedSlugs.has(rule.slug)}
                          onCheckedChange={(checked) => toggleLibrarySlug(rule.slug, !!checked)}
                        />
                        <div className="min-w-0">
                          <p className="font-medium truncate">{rule.name}</p>
                          <p className="text-xs text-muted-foreground truncate">
                            {rule.slug} - {rule.category}
                          </p>
                        </div>
                      </div>
                      <Badge variant={rule.enabled ? "default" : "secondary"}>
                        {rule.enabled ? "On" : "Off"}
                      </Badge>
                    </label>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setLibraryDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleLibraryImport}
              disabled={
                !librarySourceWorkspaceId ||
                librarySelectedSlugs.size === 0 ||
                libraryImportMutation.isPending ||
                !(canCreate || canUpdate)
              }
            >
              <LibraryBig className={`mr-2 h-4 w-4 ${libraryImportMutation.isPending ? "animate-spin" : ""}`} />
              {libraryImportMutation.isPending ? "Importing..." : "Import Selected"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={evaluateDialogOpen} onOpenChange={setEvaluateDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Evaluate Achievements</DialogTitle>
            <DialogDescription>
              Select a tournament and/or specific achievements to evaluate.
              Leave empty to evaluate all achievements across all tournaments.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Tournament selector */}
            <div className="space-y-2">
              <Label>Tournament (optional)</Label>
              <TournamentCombobox
                tournaments={tournaments?.results ?? []}
                value={evalTournamentId}
                onSelect={(t) => setEvalTournamentId(t?.id)}
                placeholder="All tournaments"
              />
            </div>

            {/* Achievement selection by category */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Achievements ({evalSelectedRuleIds.size > 0 ? `${evalSelectedRuleIds.size} selected` : "all"})</Label>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEvalSelectedRuleIds(new Set((allRules ?? []).map((r) => r.id)))}
                  >
                    Select all
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEvalSelectedRuleIds(new Set())}
                  >
                    Clear
                  </Button>
                </div>
              </div>
              <ScrollArea className="h-[50vh] rounded border p-3">
                <div className="space-y-3">
                  {Object.entries(rulesByCategory).map(([category, rules]) => {
                    const allChecked = rules.every((r) => evalSelectedRuleIds.has(r.id));
                    const someChecked = rules.some((r) => evalSelectedRuleIds.has(r.id));
                    return (
                      <div key={category}>
                        <div className="flex items-center gap-2 mb-1">
                          <Checkbox
                            checked={allChecked ? true : someChecked ? "indeterminate" : false}
                            onCheckedChange={(checked) => toggleCategory(category, !!checked)}
                          />
                          <Label className="text-sm font-medium capitalize">{category}</Label>
                          <Badge variant="secondary" className="text-xs">{rules.length}</Badge>
                        </div>
                        <div className="ml-6 grid grid-cols-2 gap-1">
                          {rules.map((rule) => (
                            <label key={rule.id} className="flex items-center gap-2 text-xs cursor-pointer">
                              <Checkbox
                                checked={evalSelectedRuleIds.has(rule.id)}
                                onCheckedChange={(checked) => toggleRule(rule.id, !!checked)}
                              />
                              <span className="truncate">{rule.slug}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setEvaluateDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleEvaluate} disabled={evaluateMutation.isPending}>
              <Play className={`mr-2 h-4 w-4 ${evaluateMutation.isPending ? "animate-spin" : ""}`} />
              {evaluateMutation.isPending ? "Evaluating..." : "Evaluate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Override Dialog ──────────────────────────────────────────────── */}
      <Dialog open={overrideDialogOpen} onOpenChange={setOverrideDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manual Achievement Override</DialogTitle>
            <DialogDescription>
              Grant or revoke an achievement for a specific user.
            </DialogDescription>
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

            <div className="space-y-2">
              <Label>Achievement</Label>
              <AchievementCombobox
                rules={allRules ?? []}
                value={overrideRuleId}
                onSelect={(rule) => setOverrideRuleId(rule?.id)}
                allowClear
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Action</Label>
                <Select value={overrideAction} onValueChange={(v) => setOverrideAction(v as "grant" | "revoke")}>
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
                placeholder="Why is this being granted/revoked manually?"
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
              disabled={!overrideUserId || !overrideRuleId || !overrideReason || overrideMutation.isPending}
            >
              {overrideMutation.isPending ? "Saving..." : overrideAction === "grant" ? "Grant Achievement" : "Revoke Achievement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Create/Edit Dialog ───────────────────────────────────────────── */}
      <EntityFormDialog
        open={createDialogOpen || !!editingRule}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setEditingRule(null);
            setFormData({ ...emptyForm });
            setImageFile(null);
            setImagePreview(null);
          }
        }}
        title={editingRule ? `Edit: ${editingRule.slug}` : "Create Achievement"}
        description={editingRule ? "Update achievement configuration and condition tree" : "Define a new achievement"}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingRule ? "Updating..." : "Creating..."}
        errorMessage={
          (editingRule ? updateMutation.error : createMutation.error) instanceof Error
            ? (editingRule ? updateMutation.error : createMutation.error)?.message
            : undefined
        }
        isDirty={isFormDirty}
      >
        <ScrollArea className="max-h-[60vh]">
          <div className="space-y-4 pr-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="slug">Slug</Label>
                <Input
                  id="slug"
                  value={(formData as AchievementRuleCreateInput).slug ?? ""}
                  onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                  placeholder="my-achievement"
                  required
                  disabled={!!editingRule}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={formData.name ?? ""}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Achievement name"
                  required
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="desc_ru">Description (RU)</Label>
                <Textarea
                  id="desc_ru"
                  value={formData.description_ru ?? ""}
                  onChange={(e) => setFormData({ ...formData, description_ru: e.target.value })}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="desc_en">Description (EN)</Label>
                <Textarea
                  id="desc_en"
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
                  onValueChange={(v) => setFormData({ ...formData, category: v as AchievementCategory })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Scope</Label>
                <Select
                  value={formData.scope ?? "global"}
                  onValueChange={(v) => setFormData({ ...formData, scope: v as AchievementScope })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SCOPES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Grain</Label>
                <Select
                  value={formData.grain ?? "user"}
                  onValueChange={(v) => setFormData({ ...formData, grain: v as AchievementGrain })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {GRAINS.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Image upload */}
            <div className="space-y-2">
              <Label>Image</Label>
              <div className="flex items-center gap-4">
                {(imagePreview || formData.image_url) && (
                  <Image
                    src={imagePreview ?? (formData.image_url as string) ?? ""}
                    alt="Achievement"
                    width={64}
                    height={64}
                    className="h-16 w-16 rounded-lg object-cover border"
                  />
                )}
                <div className="flex flex-col gap-2">
                  <input
                    ref={imageInputRef}
                    type="file"
                    accept="image/webp,image/png,image/jpeg,image/gif"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (file.size > 5 * 1024 * 1024) {
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
                    {imagePreview ? "Change Image" : "Upload Image"}
                  </Button>
                  {imagePreview && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setImageFile(null);
                        setImagePreview(null);
                      }}
                    >
                      <X className="mr-2 h-4 w-4" />
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </ScrollArea>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingRule && (
        <DeleteConfirmDialog
          open={!!deletingRule}
          onOpenChange={(open) => !open && setDeletingRule(null)}
          onConfirm={() => deleteMutation.mutate(deletingRule.id)}
          isDeleting={deleteMutation.isPending}
          title={`Delete "${deletingRule.slug}"?`}
          cascadeInfo={["All evaluation results for this achievement will also be deleted"]}
        />
      )}

      {/* Test Result Dialog */}
      <Dialog open={!!testResult} onOpenChange={(open) => !open && setTestResult(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dry-Run Result: {testResult?.slug}</DialogTitle>
            <DialogDescription>
              {testResult?.count} users qualify for this achievement
            </DialogDescription>
          </DialogHeader>
          {testResult && testResult.sample.length > 0 && (
            <div className="text-sm">
              <p className="font-medium mb-2">Sample (first 20):</p>
              <div className="max-h-48 overflow-auto rounded border p-2 bg-muted/50 font-mono text-xs">
                {testResult.sample.map((tuple, i) => (
                  <div key={i}>
                    user={tuple[0]}
                    {tuple[1] ? ` tournament=${tuple[1]}` : ""}
                    {tuple[2] ? ` match=${tuple[2]}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
