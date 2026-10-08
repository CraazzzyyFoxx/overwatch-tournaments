import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CommunityPage, communityMetadata } from "../_components/CommunityPage";
import workspaceService from "@/services/workspace.service";
import type { Workspace } from "@/types/workspace.types";

export const dynamic = "force-dynamic";

/**
 * `all`, not the public directory: a community's own page must stay reachable
 * for its members while it is still `unverified` or hidden. Cached so the
 * metadata and the page itself resolve the slug with one read.
 */
const resolveWorkspace = cache(async (slug: string): Promise<Workspace> => {
  let workspaces: Workspace[];
  try {
    workspaces = await workspaceService.getAll("all");
  } catch {
    notFound();
  }
  const workspace = workspaces.find((candidate) => candidate.slug === slug);
  if (!workspace) notFound();
  return workspace;
});

export async function generateMetadata({
  params
}: Readonly<{ params: Promise<{ slug: string }> }>): Promise<Metadata> {
  const { slug } = await params;
  return communityMetadata({ workspace: await resolveWorkspace(slug), ownHost: false });
}

export default async function WorkspacePage({
  params
}: Readonly<{ params: Promise<{ slug: string }> }>) {
  const { slug } = await params;
  return <CommunityPage workspace={await resolveWorkspace(slug)} ownHost={false} />;
}
