"use client";

import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { AdminRegistration } from "@/types/balancer-admin.types";

/** Listed registrations with no workspace member: a formation's input never holds them. */
export function countUnlinkedRegistrations(
  registrations: readonly Pick<AdminRegistration, "workspace_member_id" | "deleted_at">[]
): number {
  return registrations.filter((row) => !row.deleted_at && row.workspace_member_id == null).length;
}

/**
 * Says how many listed registrations the balance job and the draft pool leave out because they are not linked to a
 * workspace member (plan Decision 9). Renders nothing when there are none.
 */
export function UnlinkedRegistrationsNotice({ count }: Readonly<{ count: number }>) {
  const t = useTranslations("unlinkedRegistrationsNotice");
  if (count === 0) return null;
  return (
    <Alert tone="warning">
      <AlertDescription>{t("message", { count })}</AlertDescription>
    </Alert>
  );
}
