"use client";

import RegistrationSchemaForm from "@/components/registration/RegistrationSchemaForm";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import type {
  AdminRegistration,
  AdminRegistrationCreateInput,
  AdminRegistrationUpdateInput
} from "@/types/balancer-admin.types";
import type { RegistrationForm } from "@/types/registration.types";

const DIALOG_CLASS =
  "max-w-3xl gap-0 overflow-hidden border-border bg-popover p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/50 sm:rounded-xl";
const HEADER_CLASS = "border-b border-[color:var(--aqt-border-2)] px-4 py-3.5 text-left sm:px-5";
const TITLE_CLASS = "text-xl font-semibold tracking-tight text-[color:var(--aqt-fg)]";
const DESCRIPTION_CLASS =
  "mt-1 max-w-2xl text-sm leading-5 text-[color:var(--aqt-fg-muted)]";

interface RegistrationFormDialogsProps {
  tournamentId: number;
  /** The tournament's real form, or the empty admin fallback while it loads. */
  form: RegistrationForm;
  createOpen: boolean;
  onCreateOpenChange: (open: boolean) => void;
  onCreate: (payload: AdminRegistrationCreateInput) => Promise<unknown>;
  createPending: boolean;
  editingRegistration: AdminRegistration | null;
  onEditingChange: (registration: AdminRegistration | null) => void;
  onUpdate: (payload: AdminRegistrationUpdateInput) => Promise<unknown>;
  updatePending: boolean;
}

/** The two schema-form dialogs: filing a registration on someone's behalf, and
 *  editing one that already exists. */
export default function RegistrationFormDialogs({
  tournamentId,
  form,
  createOpen,
  onCreateOpenChange,
  onCreate,
  createPending,
  editingRegistration,
  onEditingChange,
  onUpdate,
  updatePending
}: Readonly<RegistrationFormDialogsProps>) {
  return (
    <>
      <Dialog open={createOpen} onOpenChange={onCreateOpenChange}>
        <DialogContent className={DIALOG_CLASS}>
          <DialogHeader className={HEADER_CLASS}>
            <DialogTitle className={TITLE_CLASS}>Create Manual Registration</DialogTitle>
            <DialogDescription className={DESCRIPTION_CLASS}>
              Registers a player on your behalf: every field stays available regardless of the
              public form config, and verified-account requirements are not enforced. Link a site
              account to prefill BattleTag, Discord and Twitch from its verified logins.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            <RegistrationSchemaForm
              mode="admin"
              tournamentId={tournamentId}
              form={form}
              onSubmit={async ({ answers, admin }) => {
                await onCreate({ ...admin, answers });
              }}
              onCancel={() => onCreateOpenChange(false)}
              submitPending={createPending}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingRegistration !== null}
        onOpenChange={(open) => {
          if (!open) {
            onEditingChange(null);
          }
        }}
      >
        <DialogContent className={DIALOG_CLASS}>
          <DialogHeader className={HEADER_CLASS}>
            <DialogTitle className={TITLE_CLASS}>Edit Registration</DialogTitle>
            <DialogDescription className={DESCRIPTION_CLASS}>
              Update balancer-facing participant data in the fixed admin editor, while keeping the
              public multi-step look and hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] space-y-4 overflow-y-auto px-4 py-3.5 sm:px-5">
            {editingRegistration && (
              // The change history used to sit here, inside this already-scrolling
              // dialog. It now lives in the row's "Change history" action, which
              // opens the shared drawer: a Radix sheet inside a Radix dialog
              // stacks two focus traps and two scroll locks on one screen.
              <RegistrationSchemaForm
                mode="admin"
                tournamentId={tournamentId}
                form={form}
                initial={editingRegistration}
                onSubmit={async ({ answers, admin }) => {
                  await onUpdate({ ...admin, answers });
                }}
                onCancel={() => onEditingChange(null)}
                submitPending={updatePending}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
