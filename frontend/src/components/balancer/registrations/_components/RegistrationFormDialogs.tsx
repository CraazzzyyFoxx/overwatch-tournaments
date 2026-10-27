"use client";

import RegistrationSchemaForm from "@/components/registration/RegistrationSchemaForm";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { usePermissions } from "@/hooks/usePermissions";
import type {
  AdminRegistration,
  AdminRegistrationCreateInput,
  AdminRegistrationUpdateInput
} from "@/types/balancer-admin.types";
import type { RegistrationForm } from "@/types/registration.types";

interface RegistrationFormDialogsProps {
  tournamentId: number;
  /** The tournament's real form, or its owner-scoped empty fallback; `null` until the tournament is known. */
  form: RegistrationForm | null;
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
  const { canAccessPermission } = usePermissions();
  // The row carries its own workspace, which is the scope its edits were
  // authorized against — closer to the truth than the ambient selection.
  const rolesLocked =
    editingRegistration !== null &&
    !canAccessPermission("registration.roles", editingRegistration.workspace_id);

  return (
    <>
      <Dialog open={createOpen} onOpenChange={onCreateOpenChange}>
        <DialogContent variant="panel" className="max-w-3xl">
          <DialogHeader variant="panel">
            <DialogTitle>Create Manual Registration</DialogTitle>
            <DialogDescription className="max-w-2xl">
              Registers a player on your behalf: every field stays available regardless of the
              public form config, and verified-account requirements are not enforced. Link a site
              account to prefill the game handle, Discord and Twitch from its verified logins.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-5 py-4">
            {form && (
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
            )}
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
        <DialogContent variant="panel" className="max-w-3xl">
          <DialogHeader variant="panel">
            <DialogTitle>Edit Registration</DialogTitle>
            <DialogDescription className="max-w-2xl">
              Update balancer-facing participant data in the fixed admin editor, while keeping the
              public multi-step look and hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] space-y-4 overflow-y-auto px-5 py-4">
            {editingRegistration && form && (
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
                rolesLocked={rolesLocked}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
