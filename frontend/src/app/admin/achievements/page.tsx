"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle,
  CircleOff,
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
import { adminColumnMeta } from "@/components/admin/admin-table-columns";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
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
  EvaluationRunRead,
} from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import {
  ACHIEVEMENT_IMAGE_ACCEPT,
  ACHIEVEMENT_IMAGE_PREVIEW_CLASS,
  MAX_ACHIEVEMENT_IMAGE_BYTES
} from "@/lib/achievement-image";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

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

function IconLabel({ icon: Icon, label }: Readonly<{ icon: LucideIcon; label: string }>) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
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
  const [importError, setImportError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [hardResetOpen, setHardResetOpen] = useState(false);
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
  const [overrideFormError, setOverrideFormError] = useState<string | null>(null);

  const canCreate = canAccessPermission("achievement.create", workspaceId);
  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const cacheKey = ["admin", "achievements", workspaceId];

  // --- Queries ---

  const { data: tournaments } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
  });

  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: ["admin", "overrides", workspaceId],
    queryFn: () => adminService.getAchievementOverrides(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: allRulesPage } = useQuery({
    queryKey: [...cacheKey, "catalog"],
    queryFn: () => adminService.getAchievementRules(workspaceId!, { per_page: -1 }),
    enabled: !!workspaceId && (evaluateDialogOpen || overrideDialogOpen || Boolean(overrides?.length)),
  });
  const allRules = allRulesPage?.results;

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
      setOverrideFormError(null);
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

  // Validated on submit rather than by disabling the button, so the reader can
  // read what is missing instead of guessing why nothing happens.
  const handleOverrideSubmit = () => {
    const missing: string[] = [];
    if (!overrideUserId) missing.push("a user");
    if (!overrideRuleId) missing.push("an achievement");
    if (!overrideReason.trim()) missing.push("a reason");
    if (missing.length > 0) {
      setOverrideFormError(`Pick ${missing.join(", ")} before saving the override.`);
      return;
    }
    setOverrideFormError(null);
    overrideMutation.mutate();
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
    setImportError(null);
    const text = await file.text();
    let parsed: AchievementRuleExportEnvelope;
    try {
      parsed = JSON.parse(text) as AchievementRuleExportEnvelope;
    } catch {
      setImportError(
        `“${file.name}” is not valid JSON. Import a file produced by Export JSON on this page, unedited.`,
      );
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
    {
      accessorKey: "id",
      header: "ID",
      size: 60,
      cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>,
    },
    {
      accessorKey: "enabled",
      header: "Status",
      size: 80,
      meta: adminColumnMeta<AchievementRule>({ align: "center" }),
      cell: ({ row }) =>
        row.original.enabled ? (
          <StatusIcon icon={CheckCircle} label="On" variant="success" />
        ) : (
          <StatusIcon icon={CircleOff} label="Off" variant="muted" />
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
    {
      accessorKey: "rule_version",
      header: "Ver",
      size: 50,
      cell: ({ row }) => <span className="tabular-nums">{row.original.rule_version}</span>,
    },
    {
      id: "conditions_count",
      header: "Conditions",
      size: 90,
      enableSorting: false,
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
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => router.push(`/admin/achievements/${rule.id}`)}>
                <Eye className="mr-2 h-4 w-4" aria-hidden />
                View details
              </DropdownMenuItem>
              {canUpdate && (
                <DropdownMenuItem
                  onClick={() => {
                    updateMutation.reset();
                    setEditingRule(rule);
                    setFormData(getFormData(rule));
                  }}
                >
                  <Pencil className="mr-2 h-4 w-4" aria-hidden />
                  Edit achievement
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => testMutation.mutate(rule.id)}>
                <TestTube className="mr-2 h-4 w-4" aria-hidden />
                Test (dry run)
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  setEvalSelectedRuleIds(new Set([rule.id]));
                  setEvalTournamentId(undefined);
                  setEvaluateDialogOpen(true);
                }}
              >
                <Play className="mr-2 h-4 w-4" aria-hidden />
                Evaluate this achievement
              </DropdownMenuItem>
              {canUpdate && (
                <DropdownMenuItem
                  onClick={() => toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled })}
                >
                  {rule.enabled ? (
                    <><EyeOff className="mr-2 h-4 w-4" aria-hidden />Disable</>
                  ) : (
                    <><Eye className="mr-2 h-4 w-4" aria-hidden />Enable</>
                  )}
                </DropdownMenuItem>
              )}
              {canUpdate && canDelete && <DropdownMenuSeparator />}
              {canDelete && (
                <DropdownMenuItem onClick={() => setDeletingRule(rule)} className="text-destructive">
                  <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                  Delete achievement
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  if (!workspaceId) {
    return (
      <div className="space-y-6">
        <AdminPageHeader
          title="Achievements"
          description="Condition-tree rules, evaluation runs and manual overrides."
        />
        <EmptyNote>
          Pick a workspace in the sidebar to load its achievement catalog.
        </EmptyNote>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Achievements"
        description="Condition-tree rules, evaluation runs and manual overrides."
        actions={
          <div className="flex gap-2">
            <input
              ref={jsonImportInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => void handleJsonImportFile(e.target.files?.[0] ?? null)}
            />
            <Button variant="outline" size="sm" onClick={() => void handleExport()}>
              <Download className="mr-2 h-4 w-4" aria-hidden />
              Export JSON
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setLibraryDialogOpen(true);
                setLibrarySelectedSlugs(new Set());
              }}
            >
              <LibraryBig className="mr-2 h-4 w-4" aria-hidden />
              Browse library
            </Button>
            {(canCreate || canUpdate) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => jsonImportInputRef.current?.click()}
                disabled={importMutation.isPending}
              >
                <Upload className={`mr-2 h-4 w-4 ${importMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Import JSON
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEvalSelectedRuleIds(new Set());
                setEvalTournamentId(undefined);
                setEvaluateDialogOpen(true);
              }}
            >
              <Play className="mr-2 h-4 w-4" aria-hidden />
              Evaluate achievements
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                overrideMutation.reset();
                setOverrideFormError(null);
                setOverrideDialogOpen(true);
              }}
            >
              <UserPlus className="mr-2 h-4 w-4" aria-hidden />
              Add manual override
            </Button>
            {canCreate && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => seedMutation.mutate()}
                disabled={seedMutation.isPending}
              >
                <Sprout className={`mr-2 h-4 w-4 ${seedMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Seed defaults
              </Button>
            )}
            {canCreate && (
              <Button
                variant="destructive"
                onClick={() => setHardResetOpen(true)}
                disabled={hardResetMutation.isPending}
              >
                <RotateCcw className={`mr-2 h-4 w-4 ${hardResetMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Hard reset
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
                <Plus className="mr-2 h-4 w-4" aria-hidden />
                Create achievement
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
              Evaluation run:{" "}
              <Badge variant={evaluationResult.status === "done" ? "success" : "destructive"}>
                {evaluationResult.status}
              </Badge>
              {evaluationResult.tournament_id && (
                <span className="ml-2 text-sm text-muted-foreground tabular-nums">
                  (tournament #{evaluationResult.tournament_id})
                </span>
              )}
            </p>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setEvaluationResult(null)}
              aria-label="Dismiss the evaluation summary"
            >
              <X className="h-4 w-4" aria-hidden />
            </Button>
          </div>
          <p className="text-sm text-muted-foreground tabular-nums">
            Evaluated {evaluationResult.rules_evaluated} · created +{evaluationResult.results_created} ·
            removed −{evaluationResult.results_removed}
          </p>
          {evaluationResult.error_message && (
            <p className="text-sm text-danger">
              The run stopped early: {evaluationResult.error_message}
            </p>
          )}
        </div>
      )}

      {importError && (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 p-4">
          <p className="text-sm text-danger">{importError}</p>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setImportError(null)}
            aria-label="Dismiss the import error"
          >
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      )}

      {importResult && (
        <div className="rounded-lg border p-4 bg-muted/50 space-y-3">
          <div className="flex items-center justify-between">
            <p className="font-medium">
              Import result
              <span className="ml-2 text-sm text-muted-foreground tabular-nums">
                created +{importResult.created} · updated {importResult.updated}
              </span>
            </p>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setImportResult(null)}
              aria-label="Dismiss the import summary"
            >
              <X className="h-4 w-4" aria-hidden />
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
        queryFn={async (page, search, pageSize, sortField, sortDir) =>
          adminService.getAchievementRules(workspaceId!, {
            page,
            per_page: pageSize,
            search: search || undefined,
            sort: sortField ?? undefined,
            order: sortDir,
          })
        }
        columns={columns}
        searchPlaceholder="Search achievements…"
        emptyMessage="No achievements found. Use “Seed defaults” to create the standard set, or “Create achievement” to start from scratch."
        onRowClick={(row) => {
          router.push(`/admin/achievements/${row.original.id}`);
        }}
      />

      {/* Overrides table */}
      {overrides && overrides.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle asChild>
              <h2>Manual overrides</h2>
            </CardTitle>
            <CardDescription>
              Achievements granted or revoked by hand, outside the evaluation engine.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Achievement</TableHead>
                  <TableHead>User</TableHead>
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
                    <TableCell className="tabular-nums">#{ov.user_id}</TableCell>
                    <TableCell>
                      <Badge variant={ov.action === "grant" ? "success" : "destructive"}>
                        {ov.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
                    <TableCell className="tabular-nums">{ov.tournament_id ?? "—"}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => deleteOverrideMutation.mutate(ov.id)}
                        disabled={deleteOverrideMutation.isPending}
                        aria-label={`Remove the ${ov.action} override on ${
                          allRules?.find((r) => r.id === ov.achievement_rule_id)?.name ??
                          `achievement #${ov.achievement_rule_id}`
                        } for user #${ov.user_id}`}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* ─── Library Dialog ───────────────────────────────────────────────── */}
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
            <DialogTitle>Achievement library</DialogTitle>
            <DialogDescription>
              Import achievements from another workspace into the current workspace.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="library-source-workspace">Source workspace</Label>
              <Select
                value={librarySourceWorkspaceId ? String(librarySourceWorkspaceId) : ""}
                onValueChange={(value) => {
                  setLibrarySourceWorkspaceId(value ? Number(value) : undefined);
                  setLibrarySelectedSlugs(new Set());
                }}
              >
                <SelectTrigger id="library-source-workspace">
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
                <p className="text-sm font-medium">
                  Achievements{" "}
                  <span className="tabular-nums text-muted-foreground">
                    ({librarySelectedSlugs.size > 0 ? `${librarySelectedSlugs.size} selected` : "none selected"})
                  </span>
                </p>
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
                  <p className="text-sm text-muted-foreground">
                    Pick a source workspace above to list the achievements you can copy.
                  </p>
                )}
                {librarySourceWorkspaceId && (libraryRules?.length ?? 0) === 0 && (
                  <p className="text-sm text-muted-foreground">
                    That workspace has no achievements to copy. Choose another source workspace.
                  </p>
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
                          aria-label={`Copy ${rule.name}`}
                        />
                        <div className="min-w-0">
                          <p className="font-medium truncate">{rule.name}</p>
                          <p className="text-xs text-muted-foreground truncate">
                            {rule.slug} · {rule.category}
                          </p>
                        </div>
                      </div>
                      {rule.enabled ? (
                        <StatusIcon icon={CheckCircle} label="On" variant="success" />
                      ) : (
                        <StatusIcon icon={CircleOff} label="Off" variant="muted" />
                      )}
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
              <LibraryBig className={`mr-2 h-4 w-4 ${libraryImportMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
              {libraryImportMutation.isPending ? "Importing…" : "Import selected"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={evaluateDialogOpen} onOpenChange={setEvaluateDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Evaluate achievements</DialogTitle>
            <DialogDescription>
              Pick a tournament, specific achievements, or both. Leave everything untouched to
              re-evaluate every achievement across every tournament.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Tournament selector */}
            <div className="space-y-2">
              <Label htmlFor="eval-tournament">Tournament (optional)</Label>
              <TournamentCombobox
                id="eval-tournament"
                tournaments={tournaments?.results ?? []}
                value={evalTournamentId}
                onSelect={(t) => setEvalTournamentId(t?.id)}
                placeholder="All tournaments"
              />
            </div>

            {/* Achievement selection by category */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">
                  Achievements{" "}
                  <span className="tabular-nums text-muted-foreground">
                    ({evalSelectedRuleIds.size > 0 ? `${evalSelectedRuleIds.size} selected` : "all"})
                  </span>
                </p>
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
                            aria-label={`Select every ${category} achievement`}
                          />
                          <span className="text-sm font-medium capitalize">{category}</span>
                          <Badge variant="secondary" className="text-xs tabular-nums">{rules.length}</Badge>
                        </div>
                        <div className="ml-6 grid grid-cols-2 gap-1">
                          {rules.map((rule) => (
                            <label key={rule.id} className="flex items-center gap-2 text-xs cursor-pointer">
                              <Checkbox
                                checked={evalSelectedRuleIds.has(rule.id)}
                                onCheckedChange={(checked) => toggleRule(rule.id, !!checked)}
                                aria-label={`Evaluate ${rule.name}`}
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
              <Play className={`mr-2 h-4 w-4 ${evaluateMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
              {evaluateMutation.isPending ? "Evaluating…" : "Run evaluation"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Override Dialog ──────────────────────────────────────────────── */}
      <Dialog open={overrideDialogOpen} onOpenChange={setOverrideDialogOpen}>
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
              <Label htmlFor="override-achievement">Achievement</Label>
              <AchievementCombobox
                id="override-achievement"
                rules={allRules ?? []}
                value={overrideRuleId}
                onSelect={(rule) => setOverrideRuleId(rule?.id)}
                allowClear
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="override-action">Action</Label>
                <Select value={overrideAction} onValueChange={(v) => setOverrideAction(v as "grant" | "revoke")}>
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
                  tournaments={tournaments?.results ?? []}
                  value={overrideTournamentId}
                  onSelect={(t) => setOverrideTournamentId(t?.id)}
                  placeholder="None"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="override-reason">Reason</Label>
              <Textarea
                id="override-reason"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Why is this being granted or revoked by hand?"
              />
            </div>

            {overrideFormError && <p className="text-sm text-danger">{overrideFormError}</p>}
            {overrideMutation.error instanceof Error && (
              <p className="text-sm text-danger">
                The override could not be saved: {overrideMutation.error.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOverrideDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleOverrideSubmit} disabled={overrideMutation.isPending}>
              {overrideMutation.isPending
                ? "Saving…"
                : overrideAction === "grant"
                  ? "Grant achievement"
                  : "Revoke achievement"}
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
        title={editingRule ? `Edit ${editingRule.slug}` : "Create achievement"}
        description={
          editingRule
            ? "Update the achievement metadata. The condition tree is edited on its detail page."
            : "Define a new achievement. Add its condition tree once it exists."
        }
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingRule ? "Updating…" : "Creating…"}
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
                <Label htmlFor="rule-category">Category</Label>
                <Select
                  value={formData.category ?? "overall"}
                  onValueChange={(v) => setFormData({ ...formData, category: v as AchievementCategory })}
                >
                  <SelectTrigger id="rule-category"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="rule-scope">Scope</Label>
                <Select
                  value={formData.scope ?? "global"}
                  onValueChange={(v) => setFormData({ ...formData, scope: v as AchievementScope })}
                >
                  <SelectTrigger id="rule-scope"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SCOPES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="rule-grain">Grain</Label>
                <Select
                  value={formData.grain ?? "user"}
                  onValueChange={(v) => setFormData({ ...formData, grain: v as AchievementGrain })}
                >
                  <SelectTrigger id="rule-grain"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {GRAINS.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Image upload */}
            <div className="space-y-2">
              <p className="text-sm font-medium">Image</p>
              <div className="flex items-center gap-4">
                {(imagePreview || formData.image_url) && (
                  <Image
                    src={imagePreview ?? (formData.image_url as string) ?? ""}
                    alt={formData.name ? `${formData.name} badge` : "Achievement badge"}
                    width={64}
                    height={64}
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
                        setImageError(
                          `“${file.name}” is ${(file.size / 1024 / 1024).toFixed(1)} MB. Pick an image under 5 MB.`,
                        );
                        return;
                      }
                      setImageError(null);
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
                    <Upload className="mr-2 h-4 w-4" aria-hidden />
                    {imagePreview ? "Change image" : "Upload image"}
                  </Button>
                  {imagePreview && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setImageFile(null);
                        setImagePreview(null);
                        setImageError(null);
                      }}
                    >
                      <X className="mr-2 h-4 w-4" aria-hidden />
                      Remove image
                    </Button>
                  )}
                </div>
              </div>
              {imageError && <p className="text-sm text-danger">{imageError}</p>}
            </div>
          </div>
        </ScrollArea>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingRule && (
        <ConfirmDialog
          open={!!deletingRule}
          onOpenChange={(open) => !open && setDeletingRule(null)}
          onConfirm={() => deleteMutation.mutate(deletingRule.id)}
          pending={deleteMutation.isPending}
          intent={{
            title: "Delete achievement",
            description: `“${deletingRule.name}” (${deletingRule.slug}) is removed from this workspace. Players keep nothing from it.`,
            confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
            tone: "danger",
            cascade: [
              "Every evaluation result awarding this achievement",
              "Manual grant and revoke overrides referencing it",
            ],
          }}
        />
      )}

      {canCreate && (
        <ConfirmDialog
          open={hardResetOpen}
          onOpenChange={setHardResetOpen}
          onConfirm={() => {
            setHardResetOpen(false);
            hardResetMutation.mutate();
          }}
          pending={hardResetMutation.isPending}
          intent={{
            title: "Hard reset achievements",
            description:
              "The rule catalog for this workspace is replaced with the defaults, every current result is cleared, and a full re-evaluation runs immediately.",
            confirmLabel: hardResetMutation.isPending ? "Resetting…" : "Hard reset",
            tone: "danger",
            cascade: ["Custom achievements that are not part of the default set"],
          }}
        />
      )}

      {/* Test Result Dialog */}
      <Dialog open={!!testResult} onOpenChange={(open) => !open && setTestResult(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dry-run result: {testResult?.slug}</DialogTitle>
            <DialogDescription>
              <span className="tabular-nums">{testResult?.count ?? 0}</span> users qualify for this
              achievement right now. Nothing was awarded.
            </DialogDescription>
          </DialogHeader>
          {testResult && testResult.sample.length > 0 && (
            <div className="text-sm">
              <p className="font-medium mb-2" id="dry-run-sample">Sample (first 20)</p>
              <div
                className="max-h-48 overflow-auto rounded border p-2 bg-muted/50 font-mono text-xs tabular-nums"
                tabIndex={0}
                role="group"
                aria-labelledby="dry-run-sample"
              >
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
