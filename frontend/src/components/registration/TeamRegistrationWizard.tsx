"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError } from "@/lib/api-error";
import { MAX_AVATAR_BYTES } from "@/lib/avatar";
import { notify } from "@/lib/notify";
import { translateRegistrationTeamError } from "@/lib/registration-team-errors";
import type { RoleCode } from "@/lib/roles";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import meService from "@/services/me.service";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationForm, RegistrationSubmitInput } from "@/types/registration.types";

import RosterSlotPicker, { type RosterSlotOption } from "./RosterSlotPicker";
import RegistrationSchemaForm from "./RegistrationSchemaForm";

interface TeamRegistrationWizardProps {
  workspaceId: number;
  tournamentId: number;
  tournamentName?: string;
  form: RegistrationForm;
  /** Slots this tournament's roster actually has, in canonical order, each with
   *  its multiplicity. A captain cannot occupy a slot the shape does not define,
   *  and the backend rejects it with `slot_not_in_shape` — offering it would be a
   *  dead end. The count is shown on the tile so the captain can see whether
   *  taking one leaves another for a teammate. */
  availableSlots: readonly RosterSlotOption[];
  onClose: () => void;
}

/**
 * Captain flow: create a team and register yourself onto it in one call.
 *
 * The team's identity — logo, name, and the captain's own slot — lives ABOVE the
 * ordinary registration wizard rather than inside it: these are team facts, not
 * registration fields, and the wizard's step machinery is driven by
 * `formConfig.built_in_fields`, which knows nothing about teams. Keeping the
 * panel outside the steps also keeps it on screen throughout, so its validation
 * is visible from the first step instead of ambushing the captain at submit.
 *
 * The captain is a member like anyone else (decision 5) — they occupy a real slot
 * and their registration goes through exactly the same validation as a solo
 * entrant, which is why this delegates rather than reimplementing.
 */
export default function TeamRegistrationWizard({
  workspaceId,
  tournamentId,
  tournamentName,
  form,
  availableSlots,
  onClose,
}: Readonly<TeamRegistrationWizardProps>) {
  const t = useTranslations("registrationTeams");
  const tErrors = useTranslations("registrationTeams.errors");
  const { user: authUser } = useAuthProfile();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [slot, setSlot] = useState<RoleCode | null>(availableSlots[0]?.code ?? null);
  const [error, setError] = useState<string | null>(null);
  // Team-name errors stay hidden until the field has been left once, so the
  // panel does not open with a red "Enter a team name" on an untouched form.
  const [nameTouched, setNameTouched] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  // The logo is staged locally and uploaded after the team exists: there is no id
  // to address until `create` returns. `EditableAvatar` renders the object URL as
  // its `src`, which is the deferred flow it documents.
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  useEffect(
    // Revokes the PREVIOUS url on replace and the last one on unmount; without
    // this every re-pick leaks a blob for the lifetime of the document.
    () => () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
    },
    [imagePreview],
  );

  const userQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: !!authUser,
    staleTime: 60_000,
  });

  /**
   * The same two rules the server enforces (`team_name_required` /
   * `team_name_invalid`), checked here so the captain is not walked through the
   * whole wizard before finding out. `team_name_taken` stays server-only — it
   * needs the tournament's roster of names.
   */
  const nameError = useMemo(() => {
    const cleaned = name.trim();
    if (!cleaned) return tErrors("team_name_required");
    if (cleaned.includes("#")) return tErrors("team_name_invalid");
    return null;
  }, [name, tErrors]);
  const showNameError = nameTouched && nameError !== null;

  const mutation = useMutation({
    mutationFn: async (registration: RegistrationSubmitInput) => {
      if (!slot) throw new Error("no slot");
      const team = await registrationTeamService.create(tournamentId, {
        name: name.trim(),
        slot_code: slot,
        registration,
      });
      if (imageFile) {
        // A second call by design (see `uploadImage`'s doc): the team must
        // survive a failed upload, so this reports the shortfall rather than
        // discarding a registration the captain has already completed. The logo
        // is changeable later from the roster panel.
        try {
          await registrationTeamService.uploadImage(team.id, imageFile);
        } catch {
          notify.warning(t("create.imageFailed"));
        }
      }
      return team;
    },
    onSuccess: async () => {
      notify.success(t("create.success"));
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registration(workspaceId, tournamentId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
        }),
      ]);
      onClose();
    },
    // A field-scoped rejection is already rendered under its own control by
    // `RegistrationSchemaForm`; the banner is for team-level failures
    // (`slot_taken`, `team_name_taken`, …), which name no field.
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.details.some((detail) => detail.field)) return;
      setError(translateRegistrationTeamError(tErrors, err));
    },
  });

  const avatarLabels = {
    change: t("create.logoChange"),
    upload: t("create.logoUpload"),
    edit: t("create.logoEdit"),
    drop: t("create.logoDrop"),
    remove: t("create.logoRemove"),
    unsupportedType: t("create.logoUnsupported"),
    tooLarge: t("create.logoTooLarge", { mb: Math.round(MAX_AVATAR_BYTES / (1024 * 1024)) }),
  };

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {error}
        </div>
      )}

      <section
        aria-labelledby="regteam-identity-heading"
        className="grid gap-4 rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4"
      >
        <h3
          id="regteam-identity-heading"
          className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]"
        >
          {t("create.identityHeading")}
        </h3>

        {/* Stacks below `sm`, where a 72px logo beside the name input crushed the
            input to ~50px and wrapped its label and error over four lines. The
            dialog is viewport-width at those sizes, so a media query tracks the
            panel's real width here. */}
        <div className="flex flex-col items-start gap-4 sm:flex-row">
          <div className="grid justify-items-center gap-1.5">
            <EditableAvatar
              src={imagePreview}
              name={name}
              size={72}
              shape="rounded"
              onSelectFile={(file) => {
                setImageFile(file);
                setImagePreview(URL.createObjectURL(file));
              }}
              onDelete={
                imagePreview
                  ? () => {
                      setImageFile(null);
                      setImagePreview(null);
                    }
                  : undefined
              }
              maxSizeBytes={MAX_AVATAR_BYTES}
              onError={(message) => notify.error(message)}
              labels={avatarLabels}
            />
            <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              {t("create.logoLabel")}
            </span>
          </div>

          <div className="grid w-full min-w-0 gap-1.5 sm:flex-1">
            <Label htmlFor="regteam-name">{t("create.nameLabel")}</Label>
            <Input
              id="regteam-name"
              ref={nameRef}
              value={name}
              maxLength={255}
              placeholder={t("create.namePlaceholder")}
              autoComplete="off"
              aria-invalid={showNameError || undefined}
              aria-describedby="regteam-name-hint"
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setNameTouched(true)}
              className={
                showNameError
                  ? "border-destructive focus-visible:ring-destructive"
                  : undefined
              }
            />
            <p
              id="regteam-name-hint"
              className={
                showNameError
                  ? "text-xs text-destructive"
                  : "text-xs text-[color:var(--aqt-fg-muted)]"
              }
            >
              {showNameError ? nameError : t("create.nameHint")}
            </p>
          </div>
        </div>

        {/* A real fieldset/legend, not a div plus `role="radiogroup"`: the radios
            already form a group, and this is the platform's way to name it. The
            grid lives on an inner wrapper because a legend inside a grid-display
            fieldset is laid out inconsistently across browsers. */}
        <fieldset className="min-w-0" aria-describedby="regteam-slot-hint">
          <legend className="text-sm font-medium">{t("create.slotLabel")}</legend>
          <div className="mt-2 grid gap-2">
            <RosterSlotPicker
              name="regteam-slot"
              options={availableSlots}
              value={slot}
              onChange={setSlot}
            />
            <p id="regteam-slot-hint" className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("create.slotHint")}
            </p>
          </div>
        </fieldset>
      </section>

      <RegistrationSchemaForm
        mode="public"
        tournamentId={tournamentId}
        form={form}
        tournamentName={tournamentName}
        // The dialog title already names the task and the tournament; a second
        // visible heading here would also put an `<h3>` above an `<h2>`.
        hideTitle
        userProfile={userQuery.data}
        // The captain's chosen slot drives the role step, so the matrix shows the
        // one row they will actually play instead of asking the question twice.
        lockedRole={slot}
        onSubmit={async ({ form_version_id, answers }) => {
          setError(null);
          if (nameError) {
            // Surface it where it belongs and move focus there, rather than
            // repeating the message in the footer far from the field.
            setNameTouched(true);
            nameRef.current?.focus();
            return;
          }
          await mutation.mutateAsync({ form_version_id, answers });
        }}
        onCancel={onClose}
        submitPending={mutation.isPending}
      />
    </div>
  );
}
