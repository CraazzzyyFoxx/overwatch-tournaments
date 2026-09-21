"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BadgeInfo, Loader2, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";

import SchemaForm, { schemaSteps, type SchemaFormFooterState } from "@/components/forms/SchemaForm";
import type { FieldRendererContext } from "@/components/forms/types";
import { AuthUserSearchCombobox, type AuthUserOption } from "@/components/kit/AuthUserSearchCombobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fieldErrorsFrom } from "@/lib/forms/form-errors";
import { visibleFields } from "@/lib/forms/visible-when";
import { notify } from "@/lib/notify";
import { ROLES, type RoleCode } from "@/lib/roles";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import heroService from "@/services/hero.service";
import registrationService from "@/services/registration.service";
import { rbacService } from "@/services/rbac.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import type { AdminRegistration, AdminRegistrationRoleInput } from "@/types/balancer-admin.types";
import type { Answers, FormField, FormSchema } from "@/types/forms.types";
import type {
  Registration,
  RegistrationForm,
  RegistrationSubmitInput,
  RoleInput,
} from "@/types/registration.types";
import type { User } from "@/types/user.types";

import FieldLabel from "./FieldLabel";
import TextField, { fieldControlClass } from "./FormField";
import SubscriptionRuleNotice from "./SubscriptionRuleNotice";
import { accountProviderFor } from "./fields/IdentityField";
import { defaultRoleAnswer, rolesParams } from "./fields/RolesField";
import { registrationRenderers } from "./registrationRenderers";
import { fromRoleSelections, toRoleSelections } from "./types";

/**
 * The non-schema half of an organizer's edit: the site account this row is
 * anchored on, the two statuses, the per-role ranks and the internal note.
 *
 * None of these are questions the form asks, which is exactly why they are not
 * schema fields — they are the organizer's own annotations of the answer.
 */
export interface AdminExtras {
  display_name: string | null;
  admin_notes: string | null;
  status: string;
  balancer_status: string;
  roles: AdminRegistrationRoleInput[];
  auth_user_id: number | null;
}

export type RegistrationFormSubmit = RegistrationSubmitInput & { admin?: AdminExtras };

interface RegistrationSchemaFormProps {
  mode: "public" | "admin";
  form: RegistrationForm;
  tournamentId: number;
  tournamentName?: string;
  /** The row being edited; absent for a fresh registration. */
  initial?: Registration | AdminRegistration | null;
  /** The registrant's own profile. Public mode only — it prefills handles. */
  userProfile?: User;
  /**
   * Fix the role/slot this registration takes, hiding the other matrix rows.
   * Used by the team flows: an invite dictates the slot, and a captain picks
   * theirs in the team section above.
   */
  lockedRole?: RoleCode | null;
  onSubmit: (input: RegistrationFormSubmit) => Promise<void>;
  onCancel: () => void;
  submitPending?: boolean;
  /**
   * Suppress the form's own `<h2>`. For a host that already names itself
   * visibly — the team-registration dialog does — the inner title is a
   * near-duplicate heading below the host's own `<h2>`.
   */
  hideTitle?: boolean;
}

/** A role row as either read model serves it. */
interface StoredRole {
  role: string;
  subrole: string | null;
  is_primary: boolean;
  priority: number;
  rank_value?: number | null;
  top_heroes?: string[] | null;
}

const STATUS_OPTIONS = [
  { value: "pending", name: "Pending" },
  { value: "approved", name: "Approved" },
  { value: "rejected", name: "Rejected" },
  { value: "withdrawn", name: "Withdrawn" },
  { value: "banned", name: "Banned" },
  { value: "insufficient_data", name: "Incomplete" },
];

const BALANCER_STATUS_OPTIONS = [
  { value: "not_in_balancer", name: "Not Added" },
  { value: "incomplete", name: "Incomplete" },
  { value: "ready", name: "Ready" },
];

/**
 * The schema as the REGISTRANT sees it.
 *
 * The public form read ships the whole document, organizers-only questions
 * included — the server strips those from a public *answer* read, not from the
 * schema itself. Rendering one would ask the registrant a question that is not
 * theirs, and the server refuses the answer.
 */
function publicSchema(schema: FormSchema): FormSchema {
  return {
    ...schema,
    sections: schema.sections.map((section) => ({
      ...section,
      fields: section.fields.filter((field) => field.visibility !== "organizers"),
    })),
  };
}

function allFields(schema: FormSchema): FormField[] {
  return schema.sections.flatMap((section) => section.fields);
}

/** Stored role rows, priority order, in the shape the `roles` answer holds. */
function roleInputsFrom(roles: readonly StoredRole[]): RoleInput[] {
  return [...roles]
    .sort((a, b) => a.priority - b.priority)
    .map((role) => ({
      role: role.role,
      ...(role.subrole ? { subrole: role.subrole } : {}),
      is_primary: role.is_primary,
      ...(role.top_heroes?.length ? { top_heroes: role.top_heroes } : {}),
    }));
}

/**
 * The answers a form opens with.
 *
 * ONE loop over the schema does the whole prefill, keyed on what each field IS
 * rather than on its name: an identity-shaped builtin takes the registrant's
 * handle for its provider, and `roles` takes the flex mode's starting matrix.
 * The four hand-copied per-provider branches this replaces had to be edited in
 * lockstep, and adding VK meant remembering all of them.
 */
function initialAnswers(
  schema: FormSchema,
  mode: "public" | "admin",
  initial: Registration | AdminRegistration | null | undefined,
  userProfile: User | undefined,
  lockedRole: RoleCode | null,
): Answers {
  const answers: Answers = { ...(initial?.answers ?? {}) };
  const accounts = mode === "public" ? (userProfile?.social_accounts ?? []) : [];

  for (const field of allFields(schema)) {
    if (field.key === "roles") {
      answers.roles = initial
        ? fromRoleSelections(toRoleSelections(roleInputsFrom(initial.roles)), lockedRole)
        : defaultRoleAnswer(rolesParams(field), lockedRole);
      continue;
    }
    // `battle_tag` is a column, not a JSON answer, so an edit reads it off the
    // top level rather than out of `answers`.
    if (field.key === "battle_tag" && initial) {
      answers.battle_tag = initial.battle_tag ?? "";
      continue;
    }
    if (answers[field.key] !== undefined) continue;

    const provider = accountProviderFor(field.key);
    const handle = provider
      ? accounts.find((account) => account.provider === provider)?.username
      : undefined;
    if (handle) answers[field.key] = handle;
  }
  return answers;
}

function initialRanks(roles: readonly StoredRole[] | undefined): Record<string, string> {
  const ranks: Record<string, string> = { tank: "", damage: "", support: "" };
  for (const role of roles ?? []) {
    if (role.rank_value != null) ranks[role.role] = String(role.rank_value);
  }
  return ranks;
}

/**
 * The registration form, public and admin alike, rendered from the schema.
 *
 * Everything the tournament asks is a field of `form.form_schema`; this
 * component owns only the answer document, the step the registrant is on and —
 * in admin mode — the organizer's own non-schema annotations. It replaced an
 * 878-line wizard whose step list, validation and payload were three parallel
 * hand-maintained copies of one field catalogue.
 */
export default function RegistrationSchemaForm({
  mode,
  form,
  tournamentId,
  tournamentName,
  initial = null,
  userProfile,
  lockedRole = null,
  onSubmit,
  onCancel,
  submitPending = false,
  hideTitle = false,
}: Readonly<RegistrationSchemaFormProps>) {
  const t = useTranslations();
  const tErrors = useTranslations("forms.errors");
  const queryClient = useQueryClient();
  const openAccountSettings = useAccountSettingsModalStore((s) => s.open);
  const isAdmin = mode === "admin";

  const schema = useMemo(
    () => (isAdmin ? form.form_schema : publicSchema(form.form_schema)),
    [isAdmin, form.form_schema],
  );
  const adminInitial = initial && "admin_notes" in initial ? initial : null;

  const [answers, setAnswers] = useState<Answers>(() =>
    initialAnswers(schema, mode, initial, userProfile, lockedRole),
  );
  const [step, setStep] = useState(0);
  // Objections stay hidden until the registrant tries to advance: the form used
  // to open with a red "BattleTag is required" and a dead Next button.
  const [showErrors, setShowErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const stepRef = useRef<HTMLDivElement>(null);

  const [displayName, setDisplayName] = useState(adminInitial?.display_name ?? "");
  const [adminNotes, setAdminNotes] = useState(adminInitial?.admin_notes ?? "");
  const [status, setStatus] = useState(adminInitial?.status ?? "approved");
  const [balancerStatus, setBalancerStatus] = useState(
    adminInitial?.balancer_status ?? "not_in_balancer",
  );
  const [ranks, setRanks] = useState<Record<string, string>>(() => initialRanks(initial?.roles));
  const [authUserId, setAuthUserId] = useState<number | undefined>(undefined);
  const [authUserLabel, setAuthUserLabel] = useState<string | undefined>(undefined);

  const rolesField = allFields(schema).find((field) => field.key === "roles");
  const topHeroesEnabled = rolesField ? rolesParams(rolesField).top_heroes.enabled : false;
  const heroesQuery = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    enabled: topHeroesEnabled,
    staleTime: 5 * 60_000,
  });

  // Public mode only: the endpoint answers for the CALLER, so it is meaningless
  // while an organizer edits somebody else's registration.
  const subscriptionQuery = useQuery({
    queryKey: tournamentQueryKeys.subscriptionStatus(tournamentId),
    queryFn: () => registrationService.getMySubscriptionStatus(tournamentId),
    enabled: !isAdmin && form.require_subscription === true,
    staleTime: 30_000,
  });
  // The server refuses this submit and no field on this form can change that:
  // anything a challenge code could still fix is asked for at check-in.
  const subscriptionBlocked = subscriptionQuery.data?.blocks_registration === true;

  const accounts = isAdmin ? [] : (userProfile?.social_accounts ?? []);
  const onLinkAccounts = isAdmin
    ? undefined
    : () => {
        // Close registration and open profile settings on the "My Account" tab;
        // linking there redirects through OAuth and returns via
        // `?settings=profile`.
        onCancel();
        openAccountSettings("profile");
      };

  const context: FieldRendererContext = {
    mode,
    accounts,
    subroleCatalog: form.subrole_catalog ?? {},
    heroes: heroesQuery.data?.results ?? [],
    lockedRole,
    subscription: isAdmin ? null : (subscriptionQuery.data ?? null),
    onLinkAccounts,
    t: tErrors,
  };

  const updateAnswer = (key: string, value: unknown) => {
    setAnswers((prev) => ({ ...prev, [key]: value }));
    // A rejection the registrant has since answered is stale advice.
    setServerErrors((prev) => {
      if (prev[key] === undefined) return prev;
      const rest = { ...prev };
      delete rest[key];
      return rest;
    });
  };

  /** Prefill the organizer's empty identity answers from the linked account's
   *  verified logins — the same one loop as the public prefill. */
  const handleSelectAuthUser = async (authUser: AuthUserOption | undefined) => {
    setAuthUserId(authUser?.id);
    setAuthUserLabel(authUser?.label);
    if (!authUser) return;
    try {
      const page = await rbacService.listOAuthConnections({
        auth_user_id: authUser.id,
        per_page: -1,
      });
      setAnswers((prev) => {
        const next = { ...prev };
        for (const field of allFields(schema)) {
          const provider = accountProviderFor(field.key);
          if (!provider) continue;
          const handle = page.results.find((c) => c.provider === provider)?.username;
          if (handle && !String(next[field.key] ?? "").trim()) next[field.key] = handle;
        }
        return next;
      });
    } catch {
      // Best-effort prefill (e.g. missing auth_user:read); linking still works.
    }
  };

  const submit = async () => {
    // Only what was asked: a hidden field's answer is not an answer, and the
    // server refuses a key its current schema does not render visible. Blank
    // answers travel too — that is how an organizer CLEARS a question.
    const sent: Answers = {};
    for (const field of visibleFields(schema, answers)) {
      sent[field.key] = answers[field.key] ?? null;
    }

    const payload: RegistrationFormSubmit = { form_version_id: form.version_id, answers: sent };
    if (isAdmin) {
      const selections = toRoleSelections(
        Array.isArray(answers.roles) ? (answers.roles as RoleInput[]) : [],
      );
      payload.admin = {
        display_name: displayName || null,
        admin_notes: adminNotes || null,
        status,
        balancer_status: balancerStatus,
        // Admin rows carry ranks and activity, which `answers.roles` cannot —
        // the server takes these over the answer when both are sent.
        roles: fromRoleSelections(selections, lockedRole).map((role, index) => {
          const typed = ranks[role.role]?.trim();
          const rank = typed ? Number(typed) : null;
          return {
            role: role.role,
            subrole: role.subrole ?? null,
            is_primary: role.is_primary,
            priority: index + 1,
            rank_value: rank != null && Number.isFinite(rank) ? rank : null,
            is_active: true,
            ...(role.top_heroes?.length ? { top_heroes: role.top_heroes } : {}),
          } as AdminRegistrationRoleInput;
        }),
        auth_user_id: authUserId ?? null,
      };
    }

    try {
      await onSubmit(payload);
    } catch (error) {
      const mapped = fieldErrorsFrom(error, tErrors);
      if (mapped.stale) {
        // The schema moved under the registrant. Refetching it is the whole
        // recovery: the form re-renders against the new version, and the
        // answers they already typed survive in state.
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: tournamentQueryKeys.registrationForm(form.workspace_id, form.tournament_id),
          }),
          queryClient.invalidateQueries({
            queryKey: ["registration-form-public", form.tournament_id],
          }),
        ]);
        notify.error(mapped.form ?? tErrors("form_version_stale"));
        return;
      }

      setServerErrors(mapped.fields);
      setShowErrors(true);
      // Land on the step the rejection belongs to; otherwise the message
      // renders on a step nobody is looking at.
      const rejected = Object.keys(mapped.fields);
      const target = schemaSteps(schema, answers).findIndex((section) =>
        section.fields.some((field) => rejected.includes(field.key)),
      );
      if (target >= 0) setStep(target);
      // A field-less rejection stays with the host: all three wizards already
      // render one banner, and the admin table has none — so it gets a toast.
      if (mapped.form && isAdmin) notify.error(mapped.form);
    }
  };

  const advance = async (state: SchemaFormFooterState) => {
    if (state.stepError) {
      setShowErrors(true);
      // Let the messages render before moving focus into one.
      requestAnimationFrame(() => {
        stepRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      });
      return;
    }
    if (!state.isLast) {
      setShowErrors(false);
      setStep((current) => current + 1);
      return;
    }
    await submit();
  };

  const organizerPanel = (
    <section className="grid gap-4 rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4">
      <h3 className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
        Organizer
      </h3>

      <div className="space-y-1.5">
        <FieldLabel label="Linked Site Account" />
        <AuthUserSearchCombobox
          value={authUserId}
          selectedLabel={authUserLabel}
          onSelect={handleSelectAuthUser}
        />
        <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">
          Optional. Anchors this registration on the selected account; empty handles are prefilled
          from its verified logins.
        </p>
      </div>

      <TextField
        label="Display Name"
        icon={<UserRound className="size-3.5 opacity-50" />}
        placeholder="Display name"
        value={displayName}
        onChange={setDisplayName}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        {ROLES.map((role) => (
          <TextField
            key={role.code}
            label={`${role.display} rank`}
            type="number"
            placeholder="—"
            value={ranks[role.code] ?? ""}
            onChange={(next) => setRanks((prev) => ({ ...prev, [role.code]: next }))}
          />
        ))}
      </div>

      <TextField
        multiline
        label="Admin Notes"
        icon={<BadgeInfo className="size-3.5 opacity-50" />}
        placeholder="Internal notes for admins only"
        value={adminNotes}
        onChange={setAdminNotes}
      />

      <AdminStatusSelect
        label="Registration Status"
        value={status}
        onChange={setStatus}
        options={STATUS_OPTIONS}
        custom={
          adminInitial?.status_meta?.kind === "custom"
            ? [{ value: adminInitial.status, name: adminInitial.status_meta.name }]
            : []
        }
      />
      <AdminStatusSelect
        label="Balancer Status"
        value={balancerStatus}
        onChange={setBalancerStatus}
        options={BALANCER_STATUS_OPTIONS}
        custom={
          adminInitial?.balancer_status_meta?.kind === "custom"
            ? [
                {
                  value: adminInitial.balancer_status,
                  name: adminInitial.balancer_status_meta.name,
                },
              ]
            : []
        }
      />
    </section>
  );

  const footer = (state: SchemaFormFooterState) => (
    <>
      {isAdmin && organizerPanel}

      {showErrors && state.stepError && (
        <p role="alert" className="text-sm text-destructive">
          {state.stepError}
        </p>
      )}

      {subscriptionBlocked && (
        <p
          role="alert"
          className="rounded-lg border border-[color:color-mix(in_srgb,var(--aqt-rose)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_12%,transparent)] p-2.5 text-xs leading-5 text-[color:var(--aqt-fg)]"
        >
          {t("common.subscription.registrationBlocked", {
            rule: subscriptionQuery.data?.rule ?? "",
          })}
        </p>
      )}

      <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] pt-4">
        <button
          type="button"
          onClick={() => {
            if (!state.canGoBack) {
              onCancel();
              return;
            }
            setShowErrors(false);
            setStep((current) => current - 1);
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          {state.canGoBack && <ArrowLeft className="size-3.5" aria-hidden />}
          {state.canGoBack
            ? isAdmin
              ? "Back"
              : t("common.back")
            : isAdmin
              ? "Cancel"
              : t("common.cancel")}
        </button>

        <button
          type="button"
          onClick={() => void advance(state)}
          disabled={submitPending || (state.isLast && subscriptionBlocked)}
          className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--aqt-teal)] px-4 py-2 text-sm font-medium text-[color:var(--aqt-bg)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50"
        >
          {submitPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {state.isLast ? (
            isAdmin ? (
              initial ? (
                "Save"
              ) : (
                "Create"
              )
            ) : (
              t("common.submit")
            )
          ) : (
            <>
              {isAdmin ? "Next" : t("common.next")}
              <ArrowRight className="size-3.5" aria-hidden />
            </>
          )}
        </button>
      </div>
    </>
  );

  return (
    <div className="flex flex-col gap-4" ref={stepRef}>
      {!isAdmin && !hideTitle && (
        <h2 className="text-lg font-semibold text-[color:var(--aqt-fg)]">
          {tournamentName
            ? t("registration.wizard.titleFor", { name: tournamentName })
            : t("registration.wizard.title")}
        </h2>
      )}

      {!isAdmin && (
        <>
          <SubscriptionRuleNotice subscription={subscriptionQuery.data} />
          {accounts.length === 0 && onLinkAccounts && (
            <button
              type="button"
              onClick={onLinkAccounts}
              className="flex w-full items-start gap-3 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-3 text-left transition-colors hover:bg-[color:var(--aqt-overlay-3)]"
            >
              <div className="space-y-0.5">
                <div className="text-sm font-medium text-[color:var(--aqt-fg)]">
                  {t("registration.accounts.noAccountsHint")}
                </div>
                <div className="text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
                  {t("registration.accounts.noAccountsHintDesc")}
                </div>
                <div className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-[color:var(--aqt-fg)]">
                  {t("registration.accounts.noAccountsHintCta")}
                  <ArrowRight className="size-3" aria-hidden />
                </div>
              </div>
            </button>
          )}
        </>
      )}

      <SchemaForm
        schema={schema}
        answers={answers}
        onChange={updateAnswer}
        renderers={registrationRenderers}
        context={context}
        serverErrors={serverErrors}
        step={step}
        onStepChange={setStep}
        showErrors={showErrors}
        footer={footer}
      />
    </div>
  );
}

function AdminStatusSelect({
  label,
  value,
  onChange,
  options,
  custom,
}: Readonly<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; name: string }>;
  custom: Array<{ value: string; name: string }>;
}>) {
  return (
    <div className="space-y-1.5">
      <FieldLabel label={label} icon={<BadgeInfo className="size-3.5 opacity-50" />} />
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className={cn(fieldControlClass, "h-9")}>
          <SelectValue placeholder={`Select ${label.toLowerCase()}`} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.name} · System
            </SelectItem>
          ))}
          {custom.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.name} · Custom
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
