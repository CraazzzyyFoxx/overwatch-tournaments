"use client";

import {
  Fragment,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useMemo,
  useState
} from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BadgeInfo,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  Globe,
  Loader2,
  Lock,
  MessageSquareText,
  Search,
  RadioTower,
  Pencil,
  ShieldBan,
  ShieldX,
  Trash2,
  Undo2,
  Upload,
  UserPlus,
  UserRound,
  X,
  XCircle
} from "lucide-react";

import UnifiedRegistrationForm from "@/components/registration/UnifiedRegistrationForm";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import BalancerRegistrationsColumnPicker from "@/app/balancer/registrations/_components/BalancerRegistrationsColumnPicker";
import RegistrationRowActions from "@/app/balancer/registrations/_components/RegistrationRowActions";
import BattleTagRankHistory from "@/components/BattleTagRankHistory";
import {
  type BalancerRegistrationColumnDefinition,
  buildBalancerRegistrationColumns
} from "@/app/balancer/registrations/_components/balancerRegistrationColumns";
import {
  type RegistrationGroupingMode,
  groupRegistrations,
  normalizeRegistrationGroupingMode
} from "@/app/balancer/registrations/_components/registrationGrouping";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useColumnVisibility } from "@/hooks/useColumnVisibility";
import { useToast } from "@/hooks/use-toast";
import { mergeStatusOptions } from "@/lib/balancer-statuses";
import { ROLE_LABELS, getSubroleLabel } from "@/lib/roles";
import balancerAdminService from "@/services/balancer-admin.service";
import registrationService from "@/services/registration.service";
import type {
  AdminGoogleSheetFeed,
  AdminRegistration,
  AdminRegistrationRole,
  BalancerRoleCode,
  BalancerRoleSubtype
} from "@/types/balancer-admin.types";
import type { RegistrationForm, SubroleCatalog } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";

type RegistrationStatusFilter = string;
type InclusionFilter = "all" | "included" | "excluded";
type SourceFilter = "all" | "manual" | "google_sheets";

const RESPONSIVE_CLASS: Record<
  NonNullable<BalancerRegistrationColumnDefinition["responsive"]>,
  string
> = {
  always: "",
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell"
};

const ALIGN_CLASS: Record<NonNullable<BalancerRegistrationColumnDefinition["align"]>, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right"
};

const ROLE_OPTIONS: BalancerRoleCode[] = ["tank", "dps", "support"];

const ADMIN_FORM_STEPS = [{ label: "Accounts" }, { label: "Roles" }, { label: "Details" }];

// Minimal fallback used only until the real registration form (with its
// workspace sub-role catalog) loads. Sub-role options are then data-driven.
const ADMIN_ROLE_FORM: RegistrationForm = {
  id: 0,
  tournament_id: 0,
  workspace_id: 0,
  is_open: true,
  opens_at: null,
  closes_at: null,
  built_in_fields: {
    primary_role: { enabled: true, required: true },
    additional_roles: { enabled: true, required: false }
  },
  custom_fields: []
};

const ADMIN_INPUT_CLASS =
  "h-9 rounded-lg border-white/10 bg-white/[0.03] px-3 text-sm text-white placeholder:text-white/28 focus-visible:ring-0 focus-visible:border-white/20";
const ADMIN_TEXTAREA_CLASS =
  "min-h-[96px] rounded-lg border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/28 focus-visible:ring-0 focus-visible:border-white/20";

const STATUS_CONFIG: Record<string, { icon: typeof Clock; className: string; label: string }> = {
  pending: { icon: Clock, className: "text-amber-500", label: "Pending" },
  approved: { icon: CheckCircle2, className: "text-emerald-500", label: "Approved" },
  rejected: { icon: XCircle, className: "text-red-500", label: "Rejected" },
  withdrawn: { icon: Undo2, className: "text-muted-foreground", label: "Withdrawn" },
  banned: { icon: ShieldBan, className: "text-red-500", label: "Banned" },
  insufficient_data: { icon: AlertTriangle, className: "text-orange-500", label: "Incomplete" }
};

function formatSubmittedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function RegistrationToggleBar({ tournamentId }: { tournamentId: number }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const searchParams = useSearchParams();

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId)
  });

  const toggleMutation = useMutation({
    mutationFn: (nextValue: boolean) =>
      balancerAdminService.upsertRegistrationForm(tournamentId, {
        is_open: nextValue,
        auto_approve: formQuery.data?.auto_approve ?? false,
        built_in_fields: formQuery.data?.built_in_fields ?? {},
        custom_fields: formQuery.data?.custom_fields ?? []
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registration-form", tournamentId]
      });
      toast({ title: formQuery.data?.is_open ? "Registration closed" : "Registration opened" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to update form", description: error.message, variant: "destructive" });
    }
  });

  const form = formQuery.data;
  const isOpen = form?.is_open ?? false;
  const formHref = searchParams.toString()
    ? `/balancer/registrations/form?${searchParams.toString()}`
    : "/balancer/registrations/form";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3">
      <div className="flex items-center gap-3">
        <Badge variant={isOpen ? "default" : "secondary"} className="gap-1.5">
          {isOpen ? <Globe className="size-3" /> : <Lock className="size-3" />}
          {isOpen ? "Open" : "Closed"}
        </Badge>
        <span className="text-sm text-muted-foreground">
          {isOpen ? "Players can register for this tournament." : "Registration is closed."}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href={formHref}>
            <Pencil className="mr-1.5 size-3.5" />
            Configure form
          </Link>
        </Button>
        <Switch
          checked={isOpen}
          onCheckedChange={(checked) => toggleMutation.mutate(checked)}
          disabled={toggleMutation.isPending || (!form && !isOpen)}
        />
      </div>
    </div>
  );
}

function RolesCell({
  roles,
  catalog
}: {
  roles: AdminRegistration["roles"];
  catalog?: SubroleCatalog;
}) {
  if (roles.length === 0) {
    return <span className="text-muted-foreground">-</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {roles
        .slice()
        .sort((left, right) => left.priority - right.priority)
        .map((role) => {
          const roleLabel = ROLE_LABELS[role.role] ?? role.role;
          const subroleLabel = role.subrole ? getSubroleLabel(catalog, role.role, role.subrole) : null;
          return (
            <div
              key={`${role.role}-${role.priority}`}
              className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
              title={[roleLabel, subroleLabel, role.rank_value != null ? `${role.rank_value}` : null]
                .filter(Boolean)
                .join(" · ")}
            >
              <span>{roleLabel}</span>
              {subroleLabel ? <span className="text-muted-foreground">{subroleLabel}</span> : null}
              {role.rank_value != null ? (
                <span className="text-muted-foreground">{role.rank_value}</span>
              ) : null}
            </div>
          );
        })}
    </div>
  );
}

function SourceBadge({ source }: { source: AdminRegistration["source"] }) {
  return (
    <Badge variant={source === "google_sheets" ? "secondary" : "outline"}>
      {source === "google_sheets" ? "Google Sheets" : "Manual"}
    </Badge>
  );
}

function BalancerBadge({ registration }: { registration: AdminRegistration }) {
  const status = registration.balancer_status ?? "not_in_balancer";
  const config: Record<string, { variant: "default" | "outline" | "destructive"; label: string }> =
    {
      not_in_balancer: { variant: "outline", label: "Not Added" },
      incomplete: { variant: "destructive", label: "Incomplete" },
      ready: { variant: "default", label: "Ready" }
    };
  const { variant, label } = config[status] ?? config.not_in_balancer;
  return <Badge variant={variant}>{label}</Badge>;
}

function CheckInBadge({ registration }: { registration: AdminRegistration }) {
  return (
    <Badge variant={registration.checked_in ? "default" : "outline"}>
      {registration.checked_in ? "Checked In" : "Not Checked In"}
    </Badge>
  );
}



function FeedStatus({ feed }: { feed: AdminGoogleSheetFeed | null | undefined }) {
  if (!feed) {
    return (
      <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
        No Google Sheets feed configured yet.
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{feed.last_sync_status ?? "pending"}</Badge>
        <span className="text-muted-foreground">
          Last sync:{" "}
          {feed.last_synced_at ? new Date(feed.last_synced_at).toLocaleString() : "never"}
        </span>
      </div>
      {feed.last_error ? <p className="mt-2 text-sm text-destructive">{feed.last_error}</p> : null}
      {feed.header_row_json?.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Headers detected: {feed.header_row_json.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

function FeedSummaryCard({
  feed,
  href
}: {
  feed: AdminGoogleSheetFeed | null | undefined;
  href: string;
}) {
  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Google Sheets Feed</CardTitle>
            <CardDescription>
              Feed configuration and mapping live on a dedicated subpage.
            </CardDescription>
          </div>
          <Button variant="outline" asChild>
            <Link href={href}>
              Open feed settings
              <ExternalLink className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <FeedStatus feed={feed} />
      </CardContent>
    </Card>
  );
}

export default function BalancerRegistrationsPage() {
  const tournamentId = useBalancerTournamentId();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<RegistrationStatusFilter>(
    (searchParams.get("status") as RegistrationStatusFilter | null) ?? "all"
  );
  const [inclusionFilter, setInclusionFilter] = useState<InclusionFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>(
    (searchParams.get("source") as SourceFilter | null) ?? "all"
  );
  const [groupBy, setGroupBy] = useState<RegistrationGroupingMode>(
    normalizeRegistrationGroupingMode(searchParams.get("group"))
  );
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [editingRegistration, setEditingRegistration] = useState<AdminRegistration | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpanded = (registrationId: number) =>
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(registrationId)) {
        next.delete(registrationId);
      } else {
        next.add(registrationId);
      }
      return next;
    });

  const registrationsQuery = useQuery({
    queryKey: [
      "balancer-admin",
      "registrations",
      tournamentId,
      statusFilter,
      inclusionFilter,
      sourceFilter
    ],
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        status_filter: statusFilter === "all" ? undefined : statusFilter,
        inclusion_filter: inclusionFilter === "all" ? undefined : inclusionFilter,
        source_filter: sourceFilter === "all" ? undefined : sourceFilter,
        include_deleted: false
      }),
    enabled: tournamentId !== null
  });

  const feedQuery = useQuery({
    queryKey: ["balancer-admin", "sheet", tournamentId],
    queryFn: () => balancerAdminService.getTournamentSheet(tournamentId as number),
    enabled: tournamentId !== null
  });

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  const publicFormQuery = useQuery({
    queryKey: ["registration-form-public", tournamentId],
    queryFn: () => registrationService.getForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  // Adapt the admin form into the public RegistrationForm shape used by the
  // shared RoleStep / sub-role catalog, so admin role editing is data-driven.
  const roleForm: RegistrationForm = useMemo(() => {
    const data = publicFormQuery.data;
    if (!data) {
      return ADMIN_ROLE_FORM;
    }
    return data;
  }, [publicFormQuery.data]);
  const subroleCatalog = roleForm.subrole_catalog;

  const requireOpenProfile = formQuery.data?.require_open_profile ?? false;

  const allColumns = useMemo(
    () => buildBalancerRegistrationColumns(subroleCatalog, requireOpenProfile),
    [subroleCatalog, requireOpenProfile]
  );
  const { visibleColumns, visibility, toggleColumn, resetToDefaults } = useColumnVisibility(
    "balancer-registrations-table-columns",
    allColumns
  );

  const customStatusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });
  const registrationStatusOptions = useMemo(
    () => mergeStatusOptions("registration", customStatusesQuery.data),
    [customStatusesQuery.data]
  );
  const balancerStatusOptions = useMemo(
    () => mergeStatusOptions("balancer", customStatusesQuery.data),
    [customStatusesQuery.data]
  );

  const invalidateRegistrations = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["balancer-admin", "registrations", tournamentId]
    });
  };

  const createMutation = useMutation({
    mutationFn: (payload: any) =>
      balancerAdminService.createManualRegistration(tournamentId as number, payload),
    onSuccess: async () => {
      await invalidateRegistrations();
      setCreateOpen(false);
      toast({ title: "Manual registration created" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to create registration",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const updateMutation = useMutation({
    mutationFn: (payload: any) => {
      if (!editingRegistration) {
        throw new Error("No registration selected");
      }
      return balancerAdminService.updateRegistration(editingRegistration.id, payload);
    },
    onSuccess: async () => {
      await invalidateRegistrations();
      setEditingRegistration(null);
      toast({ title: "Registration updated" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update registration",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const approveMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.approveRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Registration approved" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to approve", description: error.message, variant: "destructive" });
    }
  });

  const rejectMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.rejectRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Registration rejected" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to reject", description: error.message, variant: "destructive" });
    }
  });

  const withdrawMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.withdrawRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Registration withdrawn" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to withdraw", description: error.message, variant: "destructive" });
    }
  });

  const restoreMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.restoreRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Registration restored" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to restore", description: error.message, variant: "destructive" });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.deleteRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Registration deleted" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to delete", description: error.message, variant: "destructive" });
    }
  });

  const bulkApproveMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.bulkApproveRegistrations(
        tournamentId as number,
        Array.from(selectedIds)
      ),
    onSuccess: async (result) => {
      await invalidateRegistrations();
      setSelectedIds(new Set());
      toast({ title: `${result.approved} approved, ${result.skipped} skipped` });
    },
    onError: (error: Error) => {
      toast({ title: "Bulk approve failed", description: error.message, variant: "destructive" });
    }
  });

  const balancerStatusMutation = useMutation({
    mutationFn: ({
      registrationId,
      balancerStatus
    }: {
      registrationId: number;
      balancerStatus: string;
    }) => balancerAdminService.setBalancerStatus(registrationId, balancerStatus),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Balancer status updated" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update balancer status",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const checkInMutation = useMutation({
    mutationFn: ({ registrationId, checkedIn }: { registrationId: number; checkedIn: boolean }) =>
      balancerAdminService.checkInRegistration(registrationId, checkedIn),
    onSuccess: async (_, variables) => {
      await invalidateRegistrations();
      toast({ title: variables.checkedIn ? "Checked in" : "Check-in removed" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update check-in",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const bulkAddToBalancerMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.bulkAddToBalancer(tournamentId as number, Array.from(selectedIds)),
    onSuccess: async (result) => {
      await invalidateRegistrations();
      setSelectedIds(new Set());
      toast({ title: `${result.updated} added to balancer, ${result.skipped} skipped` });
    },
    onError: (error: Error) => {
      toast({
        title: "Bulk add to balancer failed",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const exportToUsersMutation = useMutation({
    mutationFn: () => balancerAdminService.exportRegistrationsToUsers(tournamentId as number),
    onSuccess: (result) => {
      toast({
        title: "Export complete",
        description: `${result.processed} processed, ${result.skipped} skipped (${result.total} total)`
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Export to analytics failed",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const registrations = registrationsQuery.data ?? [];
  const filteredRegistrations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return registrations;
    }
    return registrations.filter((registration) =>
      allColumns.some((column) => {
        if (!column.searchValue) {
          return false;
        }
        const value = column.searchValue(registration);
        return value?.toLowerCase().includes(query) ?? false;
      })
    );
  }, [allColumns, registrations, searchQuery]);
  const groupedRegistrations = useMemo(
    () => groupRegistrations(filteredRegistrations, groupBy, requireOpenProfile),
    [filteredRegistrations, groupBy, requireOpenProfile]
  );

  const selectableIds = useMemo(
    () =>
      filteredRegistrations
        .filter((registration) => registration.status === "pending")
        .map((registration) => registration.id),
    [filteredRegistrations]
  );

  const allSelectableRowsChecked =
    selectableIds.length > 0 &&
    selectableIds.every((registrationId) => selectedIds.has(registrationId));

  const pendingCount = registrations.filter(
    (registration) => registration.status === "pending"
  ).length;
  const feedHref = searchParams.toString()
    ? `/balancer/registrations/feed?${searchParams.toString()}`
    : "/balancer/registrations/feed";

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the sidebar before managing registrations.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <RegistrationToggleBar tournamentId={tournamentId} />
      <FeedSummaryCard feed={feedQuery.data} href={feedHref} />

      <Card className="flex min-h-0 flex-col overflow-hidden">
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Registrations</CardTitle>
              <CardDescription>
                {pendingCount > 0 ? `${pendingCount} pending. ` : null}
                Showing {filteredRegistrations.length} of {registrations.length}.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => exportToUsersMutation.mutate()}
                disabled={exportToUsersMutation.isPending}
              >
                {exportToUsersMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                Export to analytics
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setCreateOpen(true);
                }}
              >
                <UserPlus className="mr-2 h-4 w-4" />
                Create registration
              </Button>
              {selectedIds.size > 0 ? (
                <>
                  <Button
                    onClick={() => bulkApproveMutation.mutate()}
                    disabled={bulkApproveMutation.isPending}
                  >
                    {bulkApproveMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="mr-2 h-4 w-4" />
                    )}
                    Approve {selectedIds.size}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => bulkAddToBalancerMutation.mutate()}
                    disabled={bulkAddToBalancerMutation.isPending}
                  >
                    {bulkAddToBalancerMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="mr-2 h-4 w-4" />
                    )}
                    Add to Balancer {selectedIds.size}
                  </Button>
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/30" />
              <Input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search registrations"
                className="pl-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value)}>
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectGroup>
                  <SelectLabel>System</SelectLabel>
                  {registrationStatusOptions.system.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
                {registrationStatusOptions.custom.length > 0 ? (
                  <SelectGroup>
                    <SelectLabel>Custom</SelectLabel>
                    {registrationStatusOptions.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ) : null}
              </SelectContent>
            </Select>
            <Select
              value={inclusionFilter}
              onValueChange={(value) => setInclusionFilter(value as InclusionFilter)}
            >
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Participation" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All participation</SelectItem>
                <SelectItem value="included">Included</SelectItem>
                <SelectItem value="excluded">Excluded</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={sourceFilter}
              onValueChange={(value) => setSourceFilter(value as SourceFilter)}
            >
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Source" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="manual">Manual</SelectItem>
                <SelectItem value="google_sheets">Google Sheets</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={groupBy}
              onValueChange={(value) => setGroupBy(value as RegistrationGroupingMode)}
            >
              <SelectTrigger className="w-[190px]">
                <SelectValue placeholder="Group by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No grouping</SelectItem>
                <SelectItem value="check_in">Group by check-in</SelectItem>
                <SelectItem value="balancer_status">Group by balancer</SelectItem>
                <SelectItem value="admission">Group by admission</SelectItem>
              </SelectContent>
            </Select>
            <BalancerRegistrationsColumnPicker
              columns={allColumns}
              visibility={visibility}
              onToggle={toggleColumn}
              onReset={resetToDefaults}
            />
          </div>
        </CardHeader>

        <CardContent className="min-h-0 flex-1 overflow-auto">
          <div className="overflow-x-auto overflow-hidden rounded-xl border border-white/[0.07]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02]">
                  <th className="w-10 px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-white/40">
                    <Checkbox
                      checked={allSelectableRowsChecked}
                      onCheckedChange={(checked) =>
                        setSelectedIds((current) => {
                          const next = new Set(current);
                          if (checked) {
                            selectableIds.forEach((registrationId) => next.add(registrationId));
                          } else {
                            selectableIds.forEach((registrationId) => next.delete(registrationId));
                          }
                          return next;
                        })
                      }
                      disabled={selectableIds.length === 0}
                      aria-label="Select visible pending registrations"
                    />
                  </th>
                  {visibleColumns.map((column) => (
                    <th
                      key={column.id}
                      className={cn(
                        "px-3 py-2.5 text-xs font-medium uppercase tracking-wider text-white/40",
                        RESPONSIVE_CLASS[column.responsive ?? "always"],
                        ALIGN_CLASS[column.align ?? "left"],
                        column.widthClass
                      )}
                    >
                      {column.label}
                    </th>
                  ))}
                  <th className="w-[112px] px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wider text-white/40">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredRegistrations.length === 0 ? (
                  <tr>
                    <td
                      colSpan={visibleColumns.length + 2}
                      className="py-10 text-center text-sm text-white/40"
                    >
                      No registrations match the current filters.
                    </td>
                  </tr>
                ) : (
                  groupedRegistrations.map((group) => (
                    <Fragment key={group.key}>
                      {groupBy !== "none" ? (
                        <tr className="border-b border-white/[0.07] bg-white/[0.035]">
                          <td
                            colSpan={visibleColumns.length + 2}
                            className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-white/55"
                          >
                            <span className="text-white/80">{group.label}</span>
                            <span className="ml-2 text-white/35">
                              {group.registrations.length}{" "}
                              {group.registrations.length === 1 ? "registration" : "registrations"}
                            </span>
                          </td>
                        </tr>
                      ) : null}
                      {group.registrations.map((registration, index) => {
                        const selectable = registration.status === "pending";
                        const statusConfig =
                          STATUS_CONFIG[registration.status] ?? STATUS_CONFIG.pending;
                        const StatusIcon = statusConfig.icon;
                        const inBalancer = registration.balancer_status === "ready";
                        const isExpanded = expandedIds.has(registration.id);
                        return (
                          <Fragment key={registration.id}>
                          <tr
                            className="border-b border-white/4 transition-colors hover:bg-white/[0.02]"
                          >
                            <td className="px-3 py-2.5 align-top">
                              <div className="flex items-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => toggleExpanded(registration.id)}
                                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-white/40 hover:bg-white/5 hover:text-white"
                                  aria-label={isExpanded ? "Collapse details" : "Expand details"}
                                  aria-expanded={isExpanded}
                                >
                                  {isExpanded ? (
                                    <ChevronDown className="h-4 w-4" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" />
                                  )}
                                </button>
                                {selectable ? (
                                  <Checkbox
                                    checked={selectedIds.has(registration.id)}
                                    onCheckedChange={(checked) =>
                                      setSelectedIds((current) => {
                                        const next = new Set(current);
                                        if (checked) {
                                          next.add(registration.id);
                                        } else {
                                          next.delete(registration.id);
                                        }
                                        return next;
                                      })
                                    }
                                    aria-label={`Select registration ${registration.id}`}
                                  />
                                ) : null}
                              </div>
                            </td>
                            {visibleColumns.map((column) => (
                              <td
                                key={column.id}
                                className={cn(
                                  "px-3 py-2.5 align-top",
                                  RESPONSIVE_CLASS[column.responsive ?? "always"],
                                  ALIGN_CLASS[column.align ?? "left"],
                                  column.widthClass
                                )}
                              >
                                {column.render(registration, index)}
                              </td>
                            ))}
                            <td className="px-3 py-2.5 align-top">
                              <RegistrationRowActions
                                registration={registration}
                                onEdit={(selectedRegistration) => {
                                  setEditingRegistration(selectedRegistration);
                                }}
                                onApprove={(registrationId) =>
                                  approveMutation.mutate(registrationId)
                                }
                                onReject={(registrationId) => rejectMutation.mutate(registrationId)}
                                onToggleBalancer={(selectedRegistration) =>
                                  balancerStatusMutation.mutate({
                                    registrationId: selectedRegistration.id,
                                    balancerStatus:
                                      selectedRegistration.balancer_status === "ready"
                                        ? "not_in_balancer"
                                        : "ready"
                                  })
                                }
                                onToggleCheckIn={(selectedRegistration) =>
                                  checkInMutation.mutate({
                                    registrationId: selectedRegistration.id,
                                    checkedIn: !selectedRegistration.checked_in
                                  })
                                }
                                onWithdraw={(registrationId) =>
                                  withdrawMutation.mutate(registrationId)
                                }
                                onRestore={(registrationId) =>
                                  restoreMutation.mutate(registrationId)
                                }
                                onDelete={(registrationId) => deleteMutation.mutate(registrationId)}
                              />
                            </td>
                            {false && (
                              <>
                                <TableCell>
                                  <div className="space-y-1">
                                    <div className="font-medium">
                                      {registration.battle_tag ??
                                        registration.display_name ??
                                        `Registration #${registration.id}`}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                      {[registration.discord_nick, registration.twitch_nick]
                                        .filter(Boolean)
                                        .join(" · ") ||
                                        registration.source_record_key ||
                                        "-"}
                                    </div>
                                  </div>
                                </TableCell>
                                <TableCell>
                                  <SourceBadge source={registration.source} />
                                </TableCell>
                                <TableCell>
                                  <RolesCell roles={registration.roles} catalog={subroleCatalog} />
                                </TableCell>
                                <TableCell>
                                  <Badge variant="outline" className={statusConfig.className}>
                                    <StatusIcon className="mr-1 h-3.5 w-3.5" />
                                    {statusConfig.label}
                                  </Badge>
                                </TableCell>
                                <TableCell>
                                  <BalancerBadge registration={registration} />
                                </TableCell>
                                <TableCell>
                                  <CheckInBadge registration={registration} />
                                </TableCell>
                                <TableCell className="text-sm text-muted-foreground">
                                  {formatSubmittedAt(registration.submitted_at)}
                                </TableCell>
                                <TableCell>
                                  <div className="flex flex-wrap gap-2">
                                    {registration.status === "pending" ? (
                                      <>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => approveMutation.mutate(registration.id)}
                                        >
                                          <Check className="mr-1.5 h-3.5 w-3.5" />
                                          Approve
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => rejectMutation.mutate(registration.id)}
                                        >
                                          <X className="mr-1.5 h-3.5 w-3.5" />
                                          Reject
                                        </Button>
                                      </>
                                    ) : null}
                                    {registration.status !== "withdrawn" ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => {
                                          setEditingRegistration(registration);
                                        }}
                                      >
                                        <Pencil className="mr-1.5 h-3.5 w-3.5" />
                                        Edit
                                      </Button>
                                    ) : null}
                                    {registration.status === "approved" ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() =>
                                          balancerStatusMutation.mutate({
                                            registrationId: registration.id,
                                            balancerStatus: inBalancer ? "not_in_balancer" : "ready"
                                          })
                                        }
                                      >
                                        {inBalancer ? (
                                          <ShieldX className="mr-1.5 h-3.5 w-3.5" />
                                        ) : (
                                          <Check className="mr-1.5 h-3.5 w-3.5" />
                                        )}
                                        {inBalancer ? "Remove from Balancer" : "Add to Balancer"}
                                      </Button>
                                    ) : null}
                                    {registration.status === "approved" ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() =>
                                          checkInMutation.mutate({
                                            registrationId: registration.id,
                                            checkedIn: !registration.checked_in
                                          })
                                        }
                                      >
                                        <Check className="mr-1.5 h-3.5 w-3.5" />
                                        {registration.checked_in ? "Uncheck-in" : "Check-in"}
                                      </Button>
                                    ) : null}
                                    {registration.status === "withdrawn" ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => restoreMutation.mutate(registration.id)}
                                      >
                                        <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                                        Restore
                                      </Button>
                                    ) : (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => withdrawMutation.mutate(registration.id)}
                                      >
                                        <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                                        Withdraw
                                      </Button>
                                    )}
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => deleteMutation.mutate(registration.id)}
                                    >
                                      <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                                      Delete
                                    </Button>
                                  </div>
                                </TableCell>
                              </>
                            )}
                          </tr>
                          {isExpanded ? (
                            <tr className="border-b border-white/[0.06] bg-white/[0.015]">
                              <td colSpan={visibleColumns.length + 2} className="px-4 py-4">
                                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
                                  <div className="space-y-2">
                                    <div className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                                      Rank history
                                    </div>
                                    <BattleTagRankHistory
                                      userId={registration.user_id}
                                      battleTag={registration.battle_tag}
                                    />
                                  </div>
                                  <dl className="space-y-2 text-xs text-white/70">
                                    <div className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                                      Details
                                    </div>
                                    <div>
                                      <dt className="mb-1 text-white/40">Declared roles</dt>
                                      <dd>
                                        <RolesCell roles={registration.roles} catalog={subroleCatalog} />
                                      </dd>
                                    </div>
                                    {registration.smurf_tags_json.length > 0 ? (
                                      <div className="flex justify-between gap-3">
                                        <dt className="text-white/40">Smurfs</dt>
                                        <dd className="text-right">
                                          {registration.smurf_tags_json.join(", ")}
                                        </dd>
                                      </div>
                                    ) : null}
                                    {registration.discord_nick || registration.twitch_nick ? (
                                      <div className="flex justify-between gap-3">
                                        <dt className="text-white/40">Contact</dt>
                                        <dd className="text-right">
                                          {[registration.discord_nick, registration.twitch_nick]
                                            .filter(Boolean)
                                            .join(" · ")}
                                        </dd>
                                      </div>
                                    ) : null}
                                    <div className="flex justify-between gap-3">
                                      <dt className="text-white/40">Source</dt>
                                      <dd className="text-right">{registration.source}</dd>
                                    </div>
                                    <div className="flex justify-between gap-3">
                                      <dt className="text-white/40">Submitted</dt>
                                      <dd className="text-right">
                                        {formatSubmittedAt(registration.submitted_at)}
                                      </dd>
                                    </div>
                                    {registration.reviewed_at ? (
                                      <div className="flex justify-between gap-3">
                                        <dt className="text-white/40">Reviewed</dt>
                                        <dd className="text-right">
                                          {formatSubmittedAt(registration.reviewed_at)}
                                          {registration.reviewed_by_username
                                            ? ` · ${registration.reviewed_by_username}`
                                            : ""}
                                        </dd>
                                      </div>
                                    ) : null}
                                    {registration.notes ? (
                                      <div>
                                        <dt className="text-white/40">Notes</dt>
                                        <dd className="mt-0.5">{registration.notes}</dd>
                                      </div>
                                    ) : null}
                                    {registration.admin_notes ? (
                                      <div>
                                        <dt className="text-white/40">Admin notes</dt>
                                        <dd className="mt-0.5">{registration.admin_notes}</dd>
                                      </div>
                                    ) : null}
                                  </dl>
                                </div>
                              </td>
                            </tr>
                          ) : null}
                          </Fragment>
                        );
                      })}
                    </Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
        }}
      >
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-white/10 bg-[#06070c] p-0 text-white shadow-[0_20px_70px_rgba(0,0,0,0.48)] sm:rounded-[20px]">
          <DialogHeader className="border-b border-white/10 px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-white">
              Create Manual Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-white/50">
              Open the same multi-step visual shell used by the public flow, but keep every admin
              field available in one fixed editor.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            <UnifiedRegistrationForm
              mode="admin"
              tournamentId={tournamentId as number}
              workspaceId={workspaceId as number}
              formConfig={roleForm}
              onSubmit={async (payload) => {
                await createMutation.mutateAsync(payload);
              }}
              onCancel={() => {
                setCreateOpen(false);
              }}
              submitPending={createMutation.isPending}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingRegistration !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditingRegistration(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-white/10 bg-[#06070c] p-0 text-white shadow-[0_20px_70px_rgba(0,0,0,0.48)] sm:rounded-[20px]">
          <DialogHeader className="border-b border-white/10 px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-white">
              Edit Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-white/50">
              Update balancer-facing participant data in the fixed admin editor, while keeping the
              public multi-step look and hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            {editingRegistration && (
              <UnifiedRegistrationForm
                mode="admin"
                tournamentId={tournamentId as number}
                workspaceId={workspaceId as number}
                formConfig={roleForm}
                initialData={editingRegistration}
                onSubmit={async (payload) => {
                  await updateMutation.mutateAsync(payload);
                }}
                onCancel={() => {
                  setEditingRegistration(null);
                }}
                submitPending={updateMutation.isPending}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
