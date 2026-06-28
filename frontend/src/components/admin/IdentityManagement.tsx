"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SocialAccountsEditor } from "@/components/social/SocialAccountsEditor";
import type { User } from "@/types/user.types";

interface IdentityManagementProps {
  user: User;
  onClose: () => void;
  canEditIdentity: boolean;
  canDeleteIdentity: boolean;
}

/** Dialog wrapper around the unified social-accounts editor. */
export function IdentityManagement({
  user: initialUser,
  onClose,
  canEditIdentity,
  canDeleteIdentity
}: IdentityManagementProps) {
  const [user, setUser] = useState(initialUser);
  const [prevUserId, setPrevUserId] = useState(initialUser.id);

  if (initialUser.id !== prevUserId) {
    setPrevUserId(initialUser.id);
    setUser(initialUser);
  }

  const total = user.social_accounts?.length ?? 0;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Player Identities
            <Badge variant="outline" className="font-normal tabular-nums">
              {total}
            </Badge>
          </DialogTitle>
          <DialogDescription>{user.name}</DialogDescription>
        </DialogHeader>

        <SocialAccountsEditor
          userId={user.id}
          accounts={user.social_accounts ?? []}
          canEdit={canEditIdentity}
          canDelete={canDeleteIdentity}
          onUserUpdated={setUser}
        />
      </DialogContent>
    </Dialog>
  );
}
