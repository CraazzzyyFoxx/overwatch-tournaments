"use client";

import { CurrentWorkspaceSection } from "@/components/admin/workspace-settings/sectionMounts";

/** Notification settings of the workspace this admin is working in. */
export default function NotificationSettingsPage() {
  return <CurrentWorkspaceSection section="notifications" />;
}
