import { authServiceBase } from "@/lib/api-routes";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

export type MeResponse = {
  id: number | null;
  username: string;
  avatar_url?: string | null;
  roles: string[];
  permissions: string[];
  is_superuser: boolean;
  linked_players: Array<{
    player_id: number;
    player_name: string;
    is_primary: boolean;
    linked_at: string;
  }>;
  workspaces: Array<{
    workspace_id: number;
    slug: string;
    role: string;
    rbac_roles: string[];
    rbac_permissions: string[];
  }>;
};

const AUTH_SERVICE_URL = authServiceBase();

export async function GET() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/me`, {
      method: "GET",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json"
      }
    });

    if (response.status === 401) {
      return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
    }

    if (!response.ok) {
      return NextResponse.json(
        { detail: "Authentication service is temporarily unavailable" },
        { status: response.status >= 500 ? 503 : response.status }
      );
    }

    const me = await response.json();
    const payload: MeResponse = {
      id: typeof me.id === "number" ? me.id : null,
      username: me.username,
      avatar_url: me.avatar_url ?? null,
      roles: me.roles ?? [],
      permissions: me.permissions ?? [],
      is_superuser: me.is_superuser ?? false,
      linked_players: (me.linked_players ?? []).map(
        (player: MeResponse["linked_players"][number]) => ({
          player_id: player.player_id,
          player_name: player.player_name,
          is_primary: player.is_primary,
          linked_at: player.linked_at,
        }),
      ),
      workspaces: (me.workspaces ?? []).map(
        (workspace: MeResponse["workspaces"][number]) => ({
          workspace_id: workspace.workspace_id,
          slug: workspace.slug,
          role: workspace.role,
          rbac_roles: workspace.rbac_roles ?? [],
          rbac_permissions: workspace.rbac_permissions ?? [],
        }),
      ),
    };

    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ detail: "Authentication service is temporarily unavailable" }, { status: 503 });
  }
}
