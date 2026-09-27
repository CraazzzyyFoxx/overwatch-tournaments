import { getTranslations } from "next-intl/server";
import { BadgeCheck, Plus } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import type { Workspace } from "@/types/workspace.types";

import { accentTint, CARD_LINK_FOCUS, getWorkspaces, workspaceAccent } from "./home.helpers";

/** Every active community on the platform. Hidden entirely on a tenant host. */
export async function CommunitiesSection() {
  let workspaces: Workspace[] = [];
  try {
    workspaces = (await getWorkspaces()).filter((w) => w.is_active);
  } catch {
    return null;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {workspaces.map((workspace) => (
        <WorkspaceCard key={workspace.id} workspace={workspace} />
      ))}
      <GetWorkspaceCard />
    </div>
  );
}

export function CommunitiesSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-20 rounded-xl border border-border/60 bg-card/30 animate-pulse"
        />
      ))}
    </div>
  );
}

// `verified` and `trusted` both reach this directory (see `WorkspaceService.get_all`),
// so the badge marks the stricter tier — the one the platform team vouches for.
async function WorkspaceCard({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations();
  const accent = workspaceAccent(workspace.id);

  return (
    <HoverPrefetchLink
      href={`/workspace/${workspace.slug}`}
      className={`border border-border/60 bg-card/50 p-5 flex flex-col gap-3 hover:bg-card hover:border-border transition-all duration-150 ${CARD_LINK_FOCUS}`}
    >
      <div className="flex items-center gap-3">
        {workspace.icon_url ? (
          // Plain <img> (not next/image) to avoid remote-domain config for
          // arbitrary workspace icon hosts — same pattern as WorkspaceBrandIcon.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={workspace.icon_url}
            alt=""
            className="w-10 h-10 rounded-xl flex-shrink-0 object-cover border border-border/60"
          />
        ) : (
          <div
            aria-hidden
            className="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center font-display font-extrabold text-body tracking-[0.04em]"
            style={{
              background: accentTint(accent, 15),
              border: `1px solid ${accentTint(accent, 30)}`,
              color: accent
            }}
          >
            {workspace.name.slice(0, 2).toUpperCase()}
          </div>
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-1">
            <div className="font-semibold text-sm text-foreground truncate">{workspace.name}</div>
            {workspace.verification_status === "trusted" && (
              <BadgeCheck
                role="img"
                aria-label={t("home.trustedWorkspace")}
                className="w-3.5 h-3.5 flex-shrink-0 text-[color:var(--aqt-teal)]"
              />
            )}
          </div>
          {workspace.description && (
            <div className="text-label text-muted-foreground/60 mt-0.5 line-clamp-1">
              {workspace.description}
            </div>
          )}
        </div>
      </div>
    </HoverPrefetchLink>
  );
}

async function GetWorkspaceCard() {
  const t = await getTranslations();

  return (
    <HoverPrefetchLink
      href="/get-workspace"
      className={`border border-dashed border-border/60 bg-transparent p-5 flex flex-col gap-3 hover:bg-card/50 hover:border-border transition-all duration-150 ${CARD_LINK_FOCUS}`}
    >
      <div className="flex items-center gap-3">
        <div
          aria-hidden
          className="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center border border-dashed border-muted-foreground/30 text-muted-foreground/60"
        >
          <Plus className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="font-semibold text-sm text-foreground truncate">
            {t("home.getWorkspaceCard.title")}
          </div>
          <div className="text-label text-muted-foreground/60 mt-0.5 line-clamp-1">
            {t("home.getWorkspaceCard.description")}
          </div>
        </div>
      </div>
    </HoverPrefetchLink>
  );
}
