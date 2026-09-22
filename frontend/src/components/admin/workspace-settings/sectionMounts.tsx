"use client";

import { useParams } from "next/navigation";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { BrandingSection } from "./BrandingSection";
import { DiscordSection } from "./DiscordSection";
import { DomainSection } from "./DomainSection";
import { GeneralSection } from "./GeneralSection";
import { NotificationsSection } from "./NotificationsSection";
import { VisibilitySection } from "./VisibilitySection";
import type { WorkspaceRecordSectionKey } from "./sections";

/**
 * Each section that exists under both shells is implemented once and mounted
 * twice, so the only difference between the two is where the workspace id
 * comes from.
 */
const SECTION_COMPONENTS: Record<
  WorkspaceRecordSectionKey,
  (props: Readonly<{ workspaceId: number | null }>) => React.ReactElement
> = {
  general: GeneralSection,
  branding: BrandingSection,
  visibility: VisibilitySection,
  domain: DomainSection,
  discord: DiscordSection,
  notifications: NotificationsSection
};

/** `/admin/settings/*` — the workspace the admin is currently working in. */
export function CurrentWorkspaceSection({
  section
}: Readonly<{ section: WorkspaceRecordSectionKey }>) {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const Section = SECTION_COMPONENTS[section];
  return <Section workspaceId={workspaceId} />;
}

/** `/admin/workspaces/[id]/*` — a superuser editing someone else's workspace. */
export function RouteWorkspaceSection({
  section
}: Readonly<{ section: WorkspaceRecordSectionKey }>) {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const Section = SECTION_COMPONENTS[section];
  return <Section workspaceId={Number.isFinite(id) ? id : null} />;
}
