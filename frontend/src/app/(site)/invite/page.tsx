"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

import InviteAcceptWizard from "@/components/registration/InviteAcceptWizard";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { readInviteTokenFromHash } from "@/lib/invite-link";
import { translateRegistrationTeamError } from "@/lib/registration-team-errors";
import { isRosterSlotCode } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import registrationService from "@/services/registration.service";
import registrationTeamService from "@/services/registration-team.service";

/**
 * Where a shared team-invite link lands.
 *
 * The token arrives in the URL **fragment**, which is why this must be a client
 * page: a fragment is never sent to a server, so no server render can see it.
 * That is the point — the credential stays out of every access log and `Referer`
 * header on the way here. See `lib/invite-link.ts`.
 *
 * The preview is fetched ANONYMOUSLY and shown before any sign-in prompt. A link
 * invite exists to reach someone with no account; telling them to register before
 * telling them what they are joining is the wrong order, and is exactly what makes
 * a pasted link feel like a phishing attempt.
 */
export default function InviteLandingPage() {
  const t = useTranslations("registrationTeams");
  const tErrors = useTranslations("registrationTeams.errors");
  const tSlot = useTranslations("rosterShape.slotCodes");
  const router = useRouter();
  const { status: authStatus, user } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);

  // The fragment is browser-only state, so it is read as an external store rather
  // than into an effect: a lazy `useState` initializer would either throw during
  // the server render or hydrate a tree the server never produced. The server
  // snapshot is `null` — meaning "not read yet", which is a different answer from
  // `""` meaning "no fragment" and drives a spinner instead of a wrong verdict.
  const hash = useSyncExternalStore(subscribeToHashChange, readHash, readHashOnServer);
  const token = hash === null ? null : readInviteTokenFromHash(hash);
  const hashRead = hash !== null;

  const previewQuery = useQuery({
    queryKey: ["registration-team-invite-preview", token],
    queryFn: () => registrationTeamService.previewInvite(token as string),
    enabled: !!token,
    // A single-use credential: refetching on every window focus buys nothing and
    // spends the one request that matters if the token is being consumed elsewhere.
    refetchOnWindowFocus: false,
    retry: false,
  });

  const preview = previewQuery.data;

  // The wizard needs the tournament's registration form, and the invite is what
  // tells us which tournament that is — so this cannot be fetched any earlier.
  const formQuery = useQuery({
    queryKey: preview
      ? tournamentQueryKeys.registrationForm(preview.workspace_id, preview.tournament_id)
      : ["registration-form", "pending"],
    queryFn: () => registrationService.getForm(preview!.tournament_id),
    enabled: !!preview?.is_redeemable,
  });

  if (!hashRead || (token && previewQuery.isLoading)) {
    return (
      <Shell title={t("landing.title")}>
        <Loader2 className="size-5 animate-spin text-[color:var(--aqt-fg-muted)]" aria-hidden />
      </Shell>
    );
  }

  // Arrived without a link at all. Distinct from a broken link: the recourse is to
  // get a link, not to ask why this one failed.
  if (!token) {
    return (
      <Shell title={t("landing.title")}>
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("landing.noLink")}</p>
      </Shell>
    );
  }

  if (previewQuery.isError || !preview) {
    return (
      <Shell title={t("landing.title")}>
        <p role="alert" className="text-sm text-destructive">
          {translateRegistrationTeamError(tErrors, previewQuery.error)}
        </p>
        <Button variant="outline" onClick={() => void previewQuery.refetch()}>{t("landing.retry")}</Button>
      </Shell>
    );
  }

  // An unknown code from a newer server renders as itself rather than as a
  // missing-key error: the label is decoration, the slot is the offer.
  const slotLabel = isRosterSlotCode(preview.slot_code) ? tSlot(preview.slot_code) : preview.slot_code;

  const offer = (
    <div className="flex flex-col gap-1">
      <p className="text-base text-[color:var(--aqt-fg)]">
        {t("landing.invitedTo", { team: preview.team_name, tournament: preview.tournament_name })}
      </p>
      <p className="text-sm text-[color:var(--aqt-fg-muted)]">
        {preview.is_substitute
          ? t("landing.slotSubstitute", { slot: slotLabel })
          : t("landing.slot", { slot: slotLabel })}
      </p>
    </div>
  );

  // A dead link still explains itself. `state` says what happened to the invite;
  // an expired-but-pending row is the case a status alone cannot describe, which
  // is why redeemability travels separately.
  if (!preview.is_redeemable) {
    return (
      <Shell title={t("landing.title")}>
        {offer}
        <p className="text-sm text-warning">{t(`landing.dead.${deadReason(preview)}`)}</p>
      </Shell>
    );
  }

  // Signed out: show the offer, then the one action that unblocks it. The accept
  // write is account-bound, so there is no anonymous path past this point.
  if (authStatus !== "authenticated" || !user) {
    return (
      <Shell title={t("landing.title")}>
        {offer}
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("landing.signInHint")}</p>
        {/* No `nextPath`: the modal resolves in place and this page re-renders
            authenticated. A redirect would drop the fragment, and the fragment is
            the token. */}
        <Button type="button" onClick={() => openAuthModal()}>
          {t("landing.signInAction")}
        </Button>
      </Shell>
    );
  }

  if (formQuery.isLoading) {
    return (
      <Shell title={t("landing.title")}>
        {offer}
        <Loader2 className="size-5 animate-spin text-[color:var(--aqt-fg-muted)]" aria-hidden />
      </Shell>
    );
  }

  if (formQuery.isError) {
    return (
      <Shell title={t("landing.title")}>
        {offer}
        <p role="alert" className="text-sm text-destructive">{t("landing.formLoadError")}</p>
        <Button variant="outline" onClick={() => void formQuery.refetch()}>{t("landing.retry")}</Button>
      </Shell>
    );
  }

  // A redeemable invite whose tournament has no registration form is a broken
  // configuration, not a loading state — spinning forever would hide it.
  if (!formQuery.data) {
    return (
      <Shell title={t("landing.title")}>
        {offer}
        <p className="text-sm text-warning">{t("landing.dead.unavailable")}</p>
      </Shell>
    );
  }

  return (
    <Shell title={t("landing.title")}>
      <InviteAcceptWizard
        workspaceId={preview.workspace_id}
        tournamentId={preview.tournament_id}
        tournamentName={preview.tournament_name}
        form={formQuery.data}
        teamName={preview.team_name}
        slotCode={preview.slot_code}
        isSubstitute={preview.is_substitute}
        token={token}
        // Accepting and declining both end the same way: this page has nothing
        // left to say, and the roster the visitor just joined does.
        onClose={() => router.push(`/tournaments/${preview.tournament_id}/participants`)}
      />
    </Shell>
  );
}

/**
 * Which sentence a dead link gets.
 *
 * `expired` is not a stored state — it is a pending row past its clock — so it
 * cannot be read off `state` alone. And an unrecognised state falls back to the
 * generic line instead of interpolating a key that may not exist: a server that
 * grows a fifth invite state must not turn this page into a raw key.
 */
type DeadReason = "expired" | "accepted" | "declined" | "revoked" | "unavailable";

const DEAD_REASON_BY_STATE: Record<string, DeadReason> = {
  accepted: "accepted",
  declined: "declined",
  revoked: "revoked",
};

function deadReason(preview: { state: string; expires_at: string | null }): DeadReason {
  if (preview.state !== "pending") return DEAD_REASON_BY_STATE[preview.state] ?? "unavailable";
  return preview.expires_at ? "expired" : "unavailable";
}

function Shell({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <main className="mx-auto flex w-full max-w-lg flex-col gap-4 px-4 py-12">
      <header className="flex items-center gap-2">
        <Users className="size-5 text-[color:var(--aqt-fg-muted)]" aria-hidden />
        <h1 className="font-onest text-xl font-semibold text-[color:var(--aqt-fg)]">{title}</h1>
      </header>
      {children}
    </main>
  );
}

/**
 * The fragment as an external store.
 *
 * Subscribed rather than snapshotted once so that a visitor pasting a second link
 * into the same tab gets the second invite: `hashchange` fires without a remount,
 * and a one-shot read would leave the first invite on screen.
 */
function subscribeToHashChange(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

const readHash = () => window.location.hash;

/** Server render: the fragment is unknowable, which is not the same as empty. */
const readHashOnServer = () => null;
