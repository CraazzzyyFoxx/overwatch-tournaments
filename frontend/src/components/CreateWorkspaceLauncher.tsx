"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { CreateWorkspaceDialog } from "@/components/CreateWorkspaceDialog";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * The one entry point a plain signed-in account has into workspace creation.
 *
 * It cannot live in the admin panel: `/admin/*` is gated by
 * `hasAdminPanelAccessForProfile`, which an account that administers nothing
 * fails — so `/admin/workspaces`, dialog and all, is unreachable for exactly
 * the people self-service creation was opened for. This page is already where
 * "get your own workspace" points from the home page, so the button belongs
 * here; creating one makes its owner a workspace admin, which is what unlocks
 * the settings screens it then sends them to.
 */
export function CreateWorkspaceLauncher() {
  const t = useTranslations("getWorkspace.action");
  const router = useRouter();
  const { user } = useAuthProfile();
  const { isDenied } = usePermissions();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  const [open, setOpen] = useState(false);

  // Allow-by-default capability, revoked per account through negative RBAC. The
  // button is disabled rather than hidden: someone whose right was taken away
  // should learn that from the screen, not from a 403 after filling the form.
  const revoked = Boolean(user) && isDenied("workspace.self_create");

  return (
    <>
      <Button
        size="sm"
        className="mt-3"
        disabled={revoked}
        onClick={() => {
          if (!user) {
            openAuthModal(getCurrentPathForAuthRedirect(window.location));
            return;
          }
          setOpen(true);
        }}
      >
        {t("create")}
      </Button>
      {revoked ? <p className="mt-2 text-xs text-muted-foreground">{t("revoked")}</p> : null}
      <CreateWorkspaceDialog
        open={open}
        onOpenChange={setOpen}
        onCreated={(workspace) => {
          // The switcher list and the workspace cookie are stale the moment a
          // workspace exists that was not in them.
          void fetchWorkspaces();
          router.push(`/admin/workspaces/${workspace.id}/general`);
        }}
      />
    </>
  );
}
