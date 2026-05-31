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

import FieldLabel from "@/app/(site)/tournaments/[id]/_components/registration/FieldLabel";
import PublicRoleStep from "@/app/(site)/tournaments/[id]/_components/registration/RoleStep";
import SmurfTagsInput from "@/app/(site)/tournaments/[id]/_components/registration/SmurfTagsInput";
import StepIndicator from "@/app/(site)/tournaments/[id]/_components/registration/StepIndicator";
import type { AdditionalRole } from "@/app/(site)/tournaments/[id]/_components/registration/types";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import BalancerRegistrationsColumnPicker from "@/app/balancer/registrations/_components/BalancerRegistrationsColumnPicker";
import RegistrationRowActions from "@/app/balancer/registrations/_components/RegistrationRowActions";
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

type ManualDraft = {
  display_name: string;
  battle_tag: string;
  smurf_tags: string;
  discord_nick: string;
  twitch_nick: string;
  notes: string;
  admin_notes: string;
  is_flex: boolean;
  stream_pov: boolean;
  status: string;
  balancer_status: string;
  roles: Record<BalancerRoleCode, RoleDraft>;
};

type RoleDraft = {
  enabled: boolean;
  rank_value: string;
  subrole: BalancerRoleSubtype | "";
  is_primary: boolean;
  priority: string;
};

function createRoleDraft(role: BalancerRoleCode): RoleDraft {
  return {
    enabled: false,
    rank_value: "",
    subrole: "",
    is_primary: role === "tank",
    priority: String(ROLE_OPTIONS.indexOf(role) + 1)
  };
}

function createEmptyManualDraft(): ManualDraft {
  return {
    display_name: "",
    battle_tag: "",
    smurf_tags: "",
    discord_nick: "",
    twitch_nick: "",
    notes: "",
    admin_notes: "",
    is_flex: false,
    stream_pov: false,
    status: "approved",
    balancer_status: "not_in_balancer",
    roles: {
      tank: createRoleDraft("tank"),
      dps: createRoleDraft("dps"),
      support: createRoleDraft("support")
    }
  };
}

function buildManualDraftFromRegistration(registration: AdminRegistration): ManualDraft {
  const draft = createEmptyManualDraft();
  draft.display_name = registration.display_name ?? "";
  draft.battle_tag = registration.battle_tag ?? "";
  draft.smurf_tags = registration.smurf_tags_json.join(", ");
  draft.discord_nick = registration.discord_nick ?? "";
  draft.twitch_nick = registration.twitch_nick ?? "";
  draft.notes = registration.notes ?? "";
  draft.admin_notes = registration.admin_notes ?? "";
  draft.is_flex = registration.is_flex;
  draft.stream_pov = registration.stream_pov;
  draft.status = registration.status;
  draft.balancer_status = registration.balancer_status;

  for (const role of registration.roles) {
    draft.roles[role.role] = {
      enabled: role.is_active || role.rank_value !== null,
      rank_value: role.rank_value != null ? String(role.rank_value) : "",
      subrole: role.subrole ?? "",
      is_primary: role.is_primary,
      priority: String(role.priority + 1)
    };
  }

  return draft;
}

function normalizeSmurfTags(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildRolePayload(roles: ManualDraft["roles"], isFlex: boolean): AdminRegistrationRole[] {
  const enabledRoles = ROLE_OPTIONS.filter((role) => roles[role].enabled).sort((left, right) => {
    const leftPriority = Number(roles[left].priority) || ROLE_OPTIONS.indexOf(left) + 1;
    const rightPriority = Number(roles[right].priority) || ROLE_OPTIONS.indexOf(right) + 1;
    return leftPriority - rightPriority;
  });

  const explicitPrimary =
    enabledRoles.find((role) => roles[role].is_primary) ?? enabledRoles[0] ?? null;

  return enabledRoles.map((role, index) => {
    const draft = roles[role];
    const parsedRankValue = draft.rank_value.trim() ? Number(draft.rank_value) : null;
    return {
      role,
      subrole: draft.subrole || null,
      is_primary: isFlex || explicitPrimary === role,
      priority: Number(draft.priority) || index + 1,
      rank_value: Number.isFinite(parsedRankValue) ? parsedRankValue : null,
      is_active: true
    };
  });
}

const EMPTY_MANUAL_DRAFT: ManualDraft = createEmptyManualDraft();

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

function RegistrationProfileForm({
  draft,
  setDraft,
  step,
  form,
  registrationStatusOptions,
  balancerStatusOptions,
  onStepChange,
  onCancel,
  onSubmit,
  submitPending,
  submitLabel,
  submitIcon
}: {
  draft: ManualDraft;
  setDraft: Dispatch<SetStateAction<ManualDraft>>;
  step: number;
  form: RegistrationForm;
  registrationStatusOptions: {
    system: Array<{ value: string; name: string }>;
    custom: Array<{ value: string; name: string }>;
  };
  balancerStatusOptions: {
    system: Array<{ value: string; name: string }>;
    custom: Array<{ value: string; name: string }>;
  };
  onStepChange: (step: number) => void;
  onCancel: () => void;
  onSubmit: () => void;
  submitPending: boolean;
  submitLabel: string;
  submitIcon: ReactNode;
}) {
  const updateRoleDraft = (role: BalancerRoleCode, updater: (current: RoleDraft) => RoleDraft) => {
    setDraft((current) => ({
      ...current,
      roles: {
        ...current.roles,
        [role]: updater(current.roles[role])
      }
    }));
  };

  const primaryRoleCode: BalancerRoleCode | "" = draft.is_flex
    ? ""
    : (ROLE_OPTIONS.find((role) => draft.roles[role].enabled && draft.roles[role].is_primary) ??
      "");
  const primarySubrole = primaryRoleCode ? draft.roles[primaryRoleCode].subrole : "";
  const additionalRoles: AdditionalRole[] = !draft.is_flex
    ? ROLE_OPTIONS.filter((role) => draft.roles[role].enabled && !draft.roles[role].is_primary).map(
        (role) => ({
          code: role,
          subrole: draft.roles[role].subrole,
          topHeroes: []
        })
      )
    : [];
  const isLastStep = step === ADMIN_FORM_STEPS.length - 1;
  const canAdvance =
    step === 0
      ? draft.battle_tag.trim().length > 0
      : step === 1
        ? draft.is_flex || primaryRoleCode !== ""
        : true;

  const selectFlexProfile = () => {
    setDraft((current) => ({
      ...current,
      is_flex: true,
      roles: Object.fromEntries(
        ROLE_OPTIONS.map((role) => [
          role,
          {
            ...current.roles[role],
            enabled: true,
            is_primary: true
          }
        ])
      ) as ManualDraft["roles"]
    }));
  };

  const selectPrimaryRole = (role: BalancerRoleCode) => {
    setDraft((current) => ({
      ...current,
      is_flex: false,
      roles: Object.fromEntries(
        ROLE_OPTIONS.map((candidateRole) => [
          candidateRole,
          {
            ...current.roles[candidateRole],
            enabled: candidateRole === role ? true : current.roles[candidateRole].enabled,
            is_primary: candidateRole === role
          }
        ])
      ) as ManualDraft["roles"]
    }));
  };

  const setAdditionalRolesList = (roles: AdditionalRole[]) => {
    setDraft((current) => {
      const currentPrimaryRoleCode = current.is_flex
        ? ""
        : (ROLE_OPTIONS.find(
            (candidateRole) =>
              current.roles[candidateRole].enabled && current.roles[candidateRole].is_primary
          ) ?? "");

      return {
        ...current,
        roles: Object.fromEntries(
          ROLE_OPTIONS.map((role) => {
            const entry = roles.find((candidate) => candidate.code === role);
            const isPrimary = currentPrimaryRoleCode === role;
            return [
              role,
              {
                ...current.roles[role],
                enabled: isPrimary || Boolean(entry),
                is_primary: isPrimary,
                subrole: entry?.subrole ?? (isPrimary ? current.roles[role].subrole : "")
              }
            ];
          })
        ) as ManualDraft["roles"]
      };
    });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-5 border-b border-white/10 pb-5">
        <StepIndicator steps={ADMIN_FORM_STEPS} current={step} />
      </div>

      <div className="grid gap-6">
        {step === 0 ? (
          <section className="space-y-4">
            <div className="space-y-2">
              <FieldLabel label="Accounts" icon={<UserRound className="size-3.5" />} />
              <div>
                <h4 className="text-base font-semibold text-white">Identity and contact handles</h4>
                <p className="text-sm leading-5 text-white/45">
                  Only the registration identity fields that matter in admin editing.
                </p>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <FieldLabel label="Display Name" icon={<UserRound className="size-3.5" />} />
                <Input
                  className={ADMIN_INPUT_CLASS}
                  value={draft.display_name}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, display_name: event.target.value }))
                  }
                  placeholder="Display name"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel label="BattleTag" required icon={<BadgeInfo className="size-3.5" />} />
                <Input
                  className={ADMIN_INPUT_CLASS}
                  value={draft.battle_tag}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, battle_tag: event.target.value }))
                  }
                  placeholder="ZOZO#21416"
                />
              </div>
              <div className="space-y-2 lg:col-span-2">
                <SmurfTagsInput
                  tags={normalizeSmurfTags(draft.smurf_tags)}
                  onChange={(tags) =>
                    setDraft((current) => ({ ...current, smurf_tags: tags.join(", ") }))
                  }
                  suggestions={[]}
                  icon="/battlenet.svg"
                  label="Smurf BattleTags"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel label="Discord" icon={<MessageSquareText className="size-3.5" />} />
                <Input
                  className={ADMIN_INPUT_CLASS}
                  value={draft.discord_nick}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, discord_nick: event.target.value }))
                  }
                  placeholder="Discord nickname"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel label="Twitch" icon={<RadioTower className="size-3.5" />} />
                <Input
                  className={ADMIN_INPUT_CLASS}
                  value={draft.twitch_nick}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, twitch_nick: event.target.value }))
                  }
                  placeholder="Twitch channel"
                />
              </div>
            </div>
          </section>
        ) : null}

        {step === 1 ? (
          <section className="space-y-4">
            <div className="space-y-2">
              <FieldLabel label="Roles" icon={<RadioTower className="size-3.5" />} />
              <div>
                <h4 className="text-base font-semibold text-white">Role profile</h4>
                <p className="text-sm leading-5 text-white/45">
                  This step uses the same role selector as the public registration form.
                </p>
              </div>
            </div>

            <PublicRoleStep
              isFlex={draft.is_flex}
              primaryRole={primaryRoleCode}
              subrole={primarySubrole}
              additionalRoles={additionalRoles}
              onSetFlex={(isFlex) => {
                if (isFlex) {
                  selectFlexProfile();
                } else {
                  setDraft((current) => ({ ...current, is_flex: false }));
                }
              }}
              onSetPrimaryRole={(role) => selectPrimaryRole(role as BalancerRoleCode)}
              onSetSubrole={(subrole) => {
                if (!primaryRoleCode) {
                  return;
                }
                updateRoleDraft(primaryRoleCode as BalancerRoleCode, (current) => ({
                  ...current,
                  subrole: subrole as BalancerRoleSubtype | ""
                }));
              }}
              onSetAdditionalRoles={setAdditionalRolesList}
              primaryRoleError={null}
              secondaryRolesError={null}
              form={form}
              hideHelperText
              allHeroes={[]}
              topHeroesEnabled={false}
              maxHeroes={5}
              flexEnabled={form.built_in_fields?.flex_role?.enabled !== false}
              primaryRoleHeroes={[]}
              onSetPrimaryRoleHeroes={() => {}}
              flexHeroes={[]}
              onSetFlexHeroes={() => {}}
            />
          </section>
        ) : null}

        {step === 2 ? (
          <section className="space-y-4">
            <div className="space-y-2">
              <FieldLabel label="Details" icon={<MessageSquareText className="size-3.5" />} />
              <div>
                <h4 className="text-base font-semibold text-white">Details and notes</h4>
                <p className="text-sm leading-5 text-white/45">
                  Final step for notes and stream availability.
                </p>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <FieldLabel
                  label="Public Notes"
                  icon={<MessageSquareText className="size-3.5" />}
                />
                <Textarea
                  className={ADMIN_TEXTAREA_CLASS}
                  value={draft.notes}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, notes: event.target.value }))
                  }
                  placeholder="Visible notes for balancer-facing context"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel label="Admin Notes" icon={<BadgeInfo className="size-3.5" />} />
                <Textarea
                  className={ADMIN_TEXTAREA_CLASS}
                  value={draft.admin_notes}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, admin_notes: event.target.value }))
                  }
                  placeholder="Internal notes for admins only"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel label="Registration Status" icon={<BadgeInfo className="size-3.5" />} />
                <Select
                  value={draft.status}
                  onValueChange={(value) => setDraft((current) => ({ ...current, status: value }))}
                >
                  <SelectTrigger className={ADMIN_INPUT_CLASS}>
                    <SelectValue placeholder="Select registration status" />
                  </SelectTrigger>
                  <SelectContent>
                    {registrationStatusOptions.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · System
                      </SelectItem>
                    ))}
                    {registrationStatusOptions.custom.length > 0
                      ? registrationStatusOptions.custom.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.name} · Custom
                          </SelectItem>
                        ))
                      : null}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <FieldLabel label="Balancer Status" icon={<BadgeInfo className="size-3.5" />} />
                <Select
                  value={draft.balancer_status}
                  onValueChange={(value) =>
                    setDraft((current) => ({ ...current, balancer_status: value }))
                  }
                >
                  <SelectTrigger className={ADMIN_INPUT_CLASS}>
                    <SelectValue placeholder="Select balancer status" />
                  </SelectTrigger>
                  <SelectContent>
                    {balancerStatusOptions.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · System
                      </SelectItem>
                    ))}
                    {balancerStatusOptions.custom.length > 0
                      ? balancerStatusOptions.custom.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.name} · Custom
                          </SelectItem>
                        ))
                      : null}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3">
              <div>
                <FieldLabel label="Stream POV" icon={<RadioTower className="size-3.5" />} />
                <p className="mt-1 text-sm text-white/45">
                  Participant can provide a point-of-view stream.
                </p>
              </div>
              <Switch
                checked={draft.stream_pov}
                onCheckedChange={(checked) =>
                  setDraft((current) => ({ ...current, stream_pov: checked }))
                }
              />
            </div>
          </section>
        ) : null}

        <div className="flex flex-col gap-3 border-t border-white/10 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-white/38">
              Step {step + 1} of {ADMIN_FORM_STEPS.length}
            </p>
            <p className="mt-1 text-sm text-white/52">{ADMIN_FORM_STEPS[step]?.label}</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Button
              variant="outline"
              className="border-white/10 bg-white/[0.03] text-white hover:bg-white/[0.06] hover:text-white"
              onClick={onCancel}
            >
              Cancel
            </Button>
            <Button
              variant="outline"
              className="border-white/10 bg-white/[0.03] text-white hover:bg-white/[0.06] hover:text-white"
              onClick={() => onStepChange(Math.max(step - 1, 0))}
              disabled={step === 0}
            >
              <ArrowLeft className="mr-2 size-4" />
              Back
            </Button>
            {isLastStep ? (
              <Button
                className="min-w-[170px] bg-white text-black hover:bg-white/90"
                onClick={onSubmit}
                disabled={submitPending || !canAdvance}
              >
                {submitPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : submitIcon}
                {submitLabel}
              </Button>
            ) : (
              <Button
                className="min-w-[170px] bg-white text-black hover:bg-white/90"
                onClick={() => onStepChange(step + 1)}
                disabled={!canAdvance}
              >
                Next
                <ArrowRight className="ml-2 size-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
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
  const [createStep, setCreateStep] = useState(0);
  const [manualDraft, setManualDraft] = useState<ManualDraft>(EMPTY_MANUAL_DRAFT);
  const [editingRegistration, setEditingRegistration] = useState<AdminRegistration | null>(null);
  const [editStep, setEditStep] = useState(0);
  const [editingDraft, setEditingDraft] = useState<ManualDraft>(EMPTY_MANUAL_DRAFT);

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

  // Adapt the admin form into the public RegistrationForm shape used by the
  // shared RoleStep / sub-role catalog, so admin role editing is data-driven.
  const roleForm: RegistrationForm = useMemo(() => {
    const data = formQuery.data;
    if (!data) {
      return ADMIN_ROLE_FORM;
    }
    return {
      id: data.id,
      tournament_id: data.tournament_id,
      workspace_id: data.workspace_id,
      is_open: data.is_open,
      opens_at: data.opens_at,
      closes_at: data.closes_at,
      built_in_fields: data.built_in_fields ?? {},
      custom_fields: [],
      subrole_catalog: data.subrole_catalog
    };
  }, [formQuery.data]);
  const subroleCatalog = roleForm.subrole_catalog;

  const allColumns = useMemo(() => buildBalancerRegistrationColumns(subroleCatalog), [subroleCatalog]);
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
    mutationFn: () =>
      balancerAdminService.createManualRegistration(tournamentId as number, {
        display_name: manualDraft.display_name || null,
        battle_tag: manualDraft.battle_tag || null,
        smurf_tags_json: normalizeSmurfTags(manualDraft.smurf_tags),
        discord_nick: manualDraft.discord_nick || null,
        twitch_nick: manualDraft.twitch_nick || null,
        notes: manualDraft.notes || null,
        admin_notes: manualDraft.admin_notes || null,
        is_flex: manualDraft.is_flex,
        stream_pov: manualDraft.stream_pov,
        roles: buildRolePayload(manualDraft.roles, manualDraft.is_flex)
      }),
    onSuccess: async () => {
      await invalidateRegistrations();
      setCreateOpen(false);
      setCreateStep(0);
      setManualDraft(createEmptyManualDraft());
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
    mutationFn: () => {
      if (!editingRegistration) {
        throw new Error("No registration selected");
      }
      return balancerAdminService.updateRegistration(editingRegistration.id, {
        display_name: editingDraft.display_name || null,
        battle_tag: editingDraft.battle_tag || null,
        smurf_tags_json: normalizeSmurfTags(editingDraft.smurf_tags),
        discord_nick: editingDraft.discord_nick || null,
        twitch_nick: editingDraft.twitch_nick || null,
        notes: editingDraft.notes || null,
        admin_notes: editingDraft.admin_notes || null,
        is_flex: editingDraft.is_flex,
        stream_pov: editingDraft.stream_pov,
        status: editingDraft.status,
        balancer_status: editingDraft.balancer_status,
        roles: buildRolePayload(editingDraft.roles, editingDraft.is_flex)
      });
    },
    onSuccess: async () => {
      await invalidateRegistrations();
      setEditStep(0);
      setEditingRegistration(null);
      setEditingDraft(createEmptyManualDraft());
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
    () => groupRegistrations(filteredRegistrations, groupBy),
    [filteredRegistrations, groupBy]
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
                  setCreateStep(0);
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
                        return (
                          <tr
                            key={registration.id}
                            className="border-b border-white/4 transition-colors hover:bg-white/[0.02]"
                          >
                            <td className="px-3 py-2.5 align-top">
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
                                  setEditStep(0);
                                  setEditingRegistration(selectedRegistration);
                                  setEditingDraft(
                                    buildManualDraftFromRegistration(selectedRegistration)
                                  );
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
                                          setEditStep(0);
                                          setEditingRegistration(registration);
                                          setEditingDraft(
                                            buildManualDraftFromRegistration(registration)
                                          );
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
          if (!open) {
            setCreateStep(0);
            setManualDraft(createEmptyManualDraft());
          }
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
            <RegistrationProfileForm
              draft={manualDraft}
              setDraft={setManualDraft}
              step={createStep}
              form={roleForm}
              registrationStatusOptions={registrationStatusOptions}
              balancerStatusOptions={balancerStatusOptions}
              onStepChange={setCreateStep}
              onCancel={() => {
                setCreateOpen(false);
                setCreateStep(0);
                setManualDraft(createEmptyManualDraft());
              }}
              onSubmit={() => createMutation.mutate()}
              submitPending={createMutation.isPending}
              submitLabel="Create"
              submitIcon={<UserPlus className="mr-2 size-4" />}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingRegistration !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditStep(0);
            setEditingRegistration(null);
            setEditingDraft(createEmptyManualDraft());
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
            <RegistrationProfileForm
              draft={editingDraft}
              setDraft={setEditingDraft}
              step={editStep}
              form={roleForm}
              registrationStatusOptions={registrationStatusOptions}
              balancerStatusOptions={balancerStatusOptions}
              onStepChange={setEditStep}
              onCancel={() => {
                setEditStep(0);
                setEditingRegistration(null);
                setEditingDraft(createEmptyManualDraft());
              }}
              onSubmit={() => updateMutation.mutate()}
              submitPending={updateMutation.isPending}
              submitLabel="Save changes"
              submitIcon={<Pencil className="mr-2 size-4" />}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
