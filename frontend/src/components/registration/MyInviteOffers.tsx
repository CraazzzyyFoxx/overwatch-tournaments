"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { notify } from "@/lib/notify";
import { showsRoles } from "@/lib/roster/ontology";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { currentRegistrationNode } from "@/lib/tournament/flow-nodes";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationTeamInviteOffer } from "@/types/registration-team.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * The invites addressed TO the viewer, on the tournament they were sent for.
 *
 * A targeted invite carries no token, so no link and no landing page can reveal
 * it — this read is the only way its recipient learns it exists. Without this
 * surface the addressed invite mode is invisible and therefore dead.
 */
export default function MyInviteOffers({ tournament }: Readonly<{ tournament: Tournament }>) {
  const format = useFormatter();
  const t = useTranslations("registrationTeams");
  const tErrors = useTranslations("registrationTeams.errors");
  // The owner game's role names, the same vocabulary the roster panel and the public tab use,
  // so one tournament never shows two spellings of a slot.
  const metadata = useDisciplineMetadata(tournament.workspace_id, tournament.discipline);
  const ontology = metadata.data ?? null;
  const slotLabel = useSlotLabel(ontology);
  // A one-role game's every slot is that role: an offer is to the team, not to a slot worth naming.
  const showsSlots = showsRoles(ontology);
  const queryClient = useQueryClient();

  const { status: authStatus, user } = useAuthProfile();
  // Same derivation MyTeamSection uses: the hook exposes a status, not a boolean,
  // and `authenticated` alone can still carry an undefined profile.
  const isAuthenticated = authStatus === "authenticated" && user != null;
  const registrationNodeId = currentRegistrationNode(tournament)?.id ?? null;

  const offersQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationMyInvites(tournament.workspace_id, tournament.id, registrationNodeId ?? 0),
    queryFn: () => registrationTeamService.listMyInvites(tournament.id, registrationNodeId!),
    enabled: isAuthenticated && registrationNodeId != null,
  });

  /** Accepting moves three reads at once: this offer list, the roster the viewer
   *  just joined, and their own registration (which now names a team). */
  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationMyInvites(
          tournament.workspace_id,
          tournament.id,
          registrationNodeId ?? 0,
        ),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationTeams(tournament.workspace_id, tournament.id),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
      }),
    ]);

  /** The list is a snapshot: the server can still refuse with `player_not_free`
   *  if another captain recruited the viewer meanwhile, so failures must surface
   *  through the code→i18n map rather than be swallowed. */
  const failure = (err: unknown) => notify.error(translateRegistrationTeamError(tErrors, err));

  const acceptMutation = useMutation({
    // No registration body: an invitee who is already registered is a free agent
    // attaching, and the backend reuses that row and ignores anything sent here.
    // Hence one button and no form.
    mutationFn: (offer: RegistrationTeamInviteOffer) =>
      registrationTeamService.accept({ invite_id: offer.invite_id }),
    onSuccess: async (_result, offer) => {
      notify.success(t("offers.accepted", { team: offer.team_name }));
      await invalidate();
    },
    onError: failure,
  });

  const declineMutation = useMutation({
    mutationFn: (offer: RegistrationTeamInviteOffer) =>
      registrationTeamService.decline({ invite_id: offer.invite_id }),
    onSuccess: async () => {
      notify.success(t("offers.declined"));
      await invalidate();
    },
    onError: failure,
  });

  const busy = acceptMutation.isPending || declineMutation.isPending;

  const offers = offersQuery.data?.items ?? [];
  // This tab is public: an empty card on every visitor's screen is pure noise, so
  // the component disappears entirely when there is nothing to answer.
  if (!isAuthenticated || offers.length === 0) return null;

  return (
    <section className="relative grid gap-3 overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 shadow-md backdrop-blur-md sm:p-5">
      <Eyebrow tone="muted">{t("offers.title")}</Eyebrow>
      <ul className="grid gap-1.5">
        {offers.map((offer) => (
          <li
            key={offer.invite_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] px-3 py-2 text-sm"
          >
            <RosterSlotGlyph code={offer.slot_code} ontology={ontology} size={18} decorative />
            <span>
              {showsSlots
                ? t(offer.is_substitute ? "offers.sentenceSubstitute" : "offers.sentence", {
                    team: offer.team_name,
                    slot: slotLabel(offer.slot_code),
                  })
                : t(offer.is_substitute ? "offers.sentenceSubstituteNoSlot" : "offers.sentenceNoSlot", {
                    team: offer.team_name,
                  })}
            </span>
            {offer.expires_at && (
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("offers.expires", {
                  date: format.dateTime(new Date(offer.expires_at), { dateStyle: "medium" }),
                })}
              </span>
            )}
            <span className="ml-auto flex gap-1">
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => acceptMutation.mutate(offer)}
              >
                {t("offers.accept")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => declineMutation.mutate(offer)}
              >
                {t("offers.decline")}
              </Button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
