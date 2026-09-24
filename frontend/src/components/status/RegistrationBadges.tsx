import {
  CheckCircle2,
  Circle,
  Clock,
  HeartCrack,
  HeartHandshake,
  Lock,
  ShieldCheck,
  Unlock,
  XCircle
} from "lucide-react";
import { useTranslations } from "next-intl";
import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { SocialIcon } from "@/components/social/SocialIcon";
import {
  STATUS_TONE_PILL,
  StatusIconBadge,
  type StatusTone
} from "@/components/status/StatusIconBadge";
import { formatAdmissionReason } from "@/lib/registration/admission";
import { cn } from "@/lib/utils";
import type {
  Admission,
  StatusMeta,
  SubscriptionOutcome,
  SubscriptionProviderVerdict
} from "@/types/registration.types";

interface StatusBadgeProps {
  status?: string | null;
  meta?: StatusMeta | null;
  className?: string;
  compact?: boolean;
}

export function RegistrationStatusBadge({ status, meta, className, compact }: Readonly<StatusBadgeProps>) {
  return (
    <StatusMetaBadge
      meta={meta}
      fallbackValue={status ?? undefined}
      className={className}
      compact={compact}
    />
  );
}

export function BalancerStatusBadge({ status, meta, className, compact }: Readonly<StatusBadgeProps>) {
  return (
    <StatusMetaBadge
      meta={meta}
      fallbackValue={status ?? "not_in_balancer"}
      className={className}
      compact={compact}
    />
  );
}

interface CheckInStatusBadgeProps {
  checkedIn: boolean | undefined | null;
  className?: string;
}

export function CheckInStatusBadge({ checkedIn, className }: Readonly<CheckInStatusBadgeProps>) {
  const t = useTranslations();
  const isCheckedIn = checkedIn === true;

  return (
    <StatusIconBadge
      icon={isCheckedIn ? CheckCircle2 : Circle}
      label={isCheckedIn ? t("common.checkedIn") : t("common.notCheckedIn")}
      tone={isCheckedIn ? "positive" : "neutral"}
      className={className}
    />
  );
}

interface AdmissionStatusBadgeProps {
  /** The server's composed answer. The ONLY input: this badge used to take five
   *  raw fields plus two requirement flags and re-derive the decision itself,
   *  which is why a hand-checked-in player with a closed profile read as "Not
   *  admitted" forever. */
  admission: Admission;
  className?: string;
}

/**
 * The composed admission verdict, icon-only for dense tables.
 *
 * Switches on `admission.decision` and nothing else. The accessible name carries
 * the reasons, because a lone glyph in a table cell tells an organizer that
 * something is wrong without ever telling them what.
 */
export function AdmissionStatusBadge({
  admission,
  className
}: Readonly<AdmissionStatusBadgeProps>) {
  const t = useTranslations();

  // D4/D5: check-in is the last gate of every requirement, so a requirement
  // blocked behind it is spent, not fatal. It stays VISIBLE — a distinct glyph
  // and the reason in the label — but the tone stays positive, because the row
  // IS admitted and painting it amber would send an organizer chasing a row that
  // needs no action.
  //
  // The wording is neutral by necessity, never "granted manually": the verdicts
  // carry no as-of time, so an organizer's hand check-in and a subscription that
  // lapsed a week after a legitimate one are indistinguishable here, and
  // claiming the former would routinely accuse an organizer of something they
  // did not do.
  const isOverride = admission.decision === "admitted" && admission.overridden.length > 0;
  const why = (
    admission.decision === "not_admitted"
      ? admission.blockers
      : isOverride
        ? admission.overridden
        : []
  )
    .flatMap((requirement) => requirement.reasons)
    .map((reason) => formatAdmissionReason(t, reason))
    .join(", ");

  if (admission.decision === "not_admitted") {
    return (
      <StatusIconBadge
        icon={XCircle}
        label={
          why
            ? `${t("common.admissionStatus.notAdmitted")}: ${why}`
            : t("common.admissionStatus.notAdmitted")
        }
        tone="negative"
        className={className}
      />
    );
  }

  if (admission.decision === "pending_check_in") {
    return (
      <StatusIconBadge
        icon={Clock}
        label={t("common.admissionStatus.pendingCheckIn")}
        tone="warning"
        className={className}
      />
    );
  }

  if (isOverride) {
    return (
      <StatusIconBadge
        icon={ShieldCheck}
        label={
          why
            ? `${t("common.admissionStatus.admitted")} — ${t("common.admissionStatus.overridden")}: ${why}`
            : `${t("common.admissionStatus.admitted")} — ${t("common.admissionStatus.overridden")}`
        }
        tone="positive"
        className={className}
      />
    );
  }

  return (
    <StatusIconBadge
      icon={CheckCircle2}
      label={t("common.admissionStatus.admitted")}
      tone="positive"
      className={className}
    />
  );
}

interface ProfileStatusBadgeProps {
  /** True = public, False = closed, null/undefined = unknown / not checked yet. */
  profilesOpen: boolean | null | undefined;
  className?: string;
}

/**
 * The raw `profiles_open` SIGNAL as a tri-state chip: public, closed, or never
 * checked.
 *
 * Not the decision, and the comparisons below are not a copy of the admission
 * rule — whether the player is in comes from `admission.decision` and nowhere
 * else. A closed profile behind a completed check-in is still an admitted row,
 * which is exactly why this chip and `AdmissionStatusBadge` read different
 * fields and must stay separate.
 */
export function ProfileStatusBadge({ profilesOpen, className }: Readonly<ProfileStatusBadgeProps>) {
  const t = useTranslations();

  if (profilesOpen === true) {
    return (
      <StatusIconBadge
        icon={Unlock}
        label={t("common.profileOpen")}
        tone="positive"
        className={className}
      />
    );
  }
  if (profilesOpen === false) {
    return (
      <StatusIconBadge
        icon={Lock}
        label={t("common.profileClosed")}
        tone="negative"
        className={className}
      />
    );
  }
  return (
    <StatusIconBadge
      icon={Circle}
      label={t("common.profileNotChecked")}
      tone="neutral"
      className={className}
    />
  );
}


interface SubscriptionStatusBadgeProps {
  /** Composed outcome from the server; null/undefined = not required or unknown. */
  outcome: SubscriptionOutcome | null | undefined;
  className?: string;
}

/**
 * The COMPOSED subscription verdict, for admin tables and the admission column.
 *
 * Renders three states, not two: an outage must be visually distinct from a
 * confirmed refusal, because only the latter blocks. Per-provider detail belongs
 * in the row detail (see `SubscriptionProviderBadge`) — one column per provider
 * would not scale, and under `any` mode a red provider cell beside a green one
 * reads as a failure when it is not.
 *
 * This renders a SIGNAL, never the decision. `outcome === "refused"` below is not
 * a copy of the admission rule and must not be consolidated into one: whether the
 * player is in comes from `admission.decision` and nowhere else, and a refused
 * subscription an organizer has already checked the player in past is still an
 * admitted row. That is why `subscription_outcome` stays on the read beside
 * `admission` rather than being folded into it.
 */
export function SubscriptionStatusBadge({ outcome, className }: Readonly<SubscriptionStatusBadgeProps>) {
  const t = useTranslations();

  if (outcome === "satisfied") {
    return (
      <StatusIconBadge
        icon={HeartHandshake}
        label={t("common.subscription.satisfied")}
        tone="positive"
        className={className}
      />
    );
  }
  if (outcome === "refused") {
    return (
      <StatusIconBadge
        icon={HeartCrack}
        label={t("common.subscription.refused")}
        tone="negative"
        className={className}
      />
    );
  }
  return (
    <StatusIconBadge
      icon={Circle}
      label={t("common.subscription.undetermined")}
      tone="neutral"
      className={className}
    />
  );
}

interface SubscriptionProviderBadgeProps {
  provider: string;
  providerLabel: string;
  verdict: SubscriptionProviderVerdict | undefined;
  className?: string;
}

/**
 * One provider's verdict, for the registration form's account rows.
 *
 * Labelled, not icon-only: this chip is the only place a registrant learns
 * whether their subscription counts, and a lone glyph whose meaning lives in
 * `title` says nothing on touch and nothing beside a form field. The composed
 * badge above stays icon-only because it sits in dense admin tables.
 *
 * Shows the provider's own tier label rather than the numeric rank: Boosty
 * "Уровень 2" and Twitch "Tier 2" are unrelated scales and a bare number would
 * imply they are comparable.
 */
export function SubscriptionProviderBadge({
  provider,
  providerLabel,
  verdict,
  className
}: Readonly<SubscriptionProviderBadgeProps>) {
  const t = useTranslations();

  let icon = Circle;
  let tone: StatusTone = "neutral";
  let detail = t("common.subscription.unchecked");
  if (verdict?.state === "active") {
    icon = HeartHandshake;
    tone = "positive";
    detail = verdict.tier_label ?? t("common.subscription.active");
  } else if (verdict?.state === "inactive") {
    icon = HeartCrack;
    tone = "negative";
    detail = t("common.subscription.none");
  }
  const Icon = icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-label font-medium",
        STATUS_TONE_PILL[tone],
        className
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <SocialIcon provider={provider} size={12} className="shrink-0" decorative />
      {`${providerLabel}: ${detail}`}
    </span>
  );
}