"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { ArrowRight, Copy, Swords } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { HeroCoord, PageHero } from "@/components/site/PageHero";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { withReturnTo } from "@/lib/auth/return-to";
import scrimService from "@/services/scrim.service";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { ScrimListScope, ScrimRoom } from "@/types/scrim.types";

import { ScrimCreateDialog } from "./_components/ScrimCreateDialog";
import { scrimQueryKeys } from "@/lib/scrims/query-keys";

function RoomCard({
  room,
  communityName,
  onClose,
  isClosing
}: Readonly<{
  room: ScrimRoom;
  communityName?: string;
  onClose: () => void;
  isClosing: boolean;
}>) {
  const t = useTranslations("scrims.list");
  const format = useFormatter();
  const href = withReturnTo(`/scrims/${room.token}`, "/scrims");

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-onest truncate text-base font-semibold">{room.label}</h2>
            <Badge variant="secondary">{t("bestOf", { count: room.best_of })}</Badge>
            {communityName ? <Badge variant="outline">{communityName}</Badge> : null}
            {room.closed_at != null ? (
              <Badge variant="outline">{t("closed")}</Badge>
            ) : room.away_team.captain_claimed ? null : (
              <Badge variant="outline">{t("awaitingOpponent")}</Badge>
            )}
          </div>
          <p className="text-muted-foreground mt-1 truncate text-sm">
            {t("sides", { home: room.home_team.name, away: room.away_team.name })}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {t("createdAt", {
              date: format.dateTime(new Date(room.created_at), {
                dateStyle: "medium",
                timeStyle: "short"
              })
            })}
            {room.viewer_side != null
              ? ` · ${t(room.viewer_side === "home" ? "youAreHome" : "youAreAway")}`
              : null}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              // The share link is the whole joining mechanism, so it is one click
              // away from every room rather than something to reconstruct by hand.
              void navigator.clipboard
                .writeText(`${window.location.origin}/scrims/${room.token}`)
                .then(() => notify.success(t("linkCopied")))
                .catch(() => notify.error(t("linkCopyFailed")));
            }}
          >
            <Copy aria-hidden className="size-4" />
            {t("copyLink")}
          </Button>
          {/* The server's own rule, not a client re-derivation: a creator who
              plays no side, and workspace staff, may close too. */}
          {room.can_close ? (
            <Button variant="ghost" size="sm" onClick={onClose} disabled={isClosing}>
              {t("close")}
            </Button>
          ) : null}
          <Button size="sm" asChild>
            <Link href={href}>
              {t("openRoom")}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The viewer's scrim rooms, plus the form that creates one.
 *
 * Reads `ScrimRoom` directly rather than `/encounters?scope=my_team`: scrim
 * teams carry no `Player` rows, and that browse hard-excludes hidden
 * tournaments, which the scrims container always is.
 */
export default function ScrimsPage() {
  const t = useTranslations("scrims");
  const { user, status } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const statsScope = useWorkspaceStore((state) => state.statsScope);
  const hostLockedWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const workspacesLoading = useWorkspaceStore((state) => state.isLoading);
  const isAll = statsScope === "all" && hostLockedWorkspaceId == null;
  const { hasWorkspacePermission } = usePermissions();
  const queryClient = useQueryClient();

  const accessibleWorkspaceIds = user?.isSuperuser
    ? workspaces.map((workspace) => workspace.id)
    : (user?.workspaces.map((workspace) => workspace.workspace_id) ?? []);
  const listWorkspaceIds = isAll
    ? accessibleWorkspaceIds
    : [hostLockedWorkspaceId ?? workspaceId].filter(
        (id): id is number => id != null && (user?.isSuperuser || accessibleWorkspaceIds.includes(id))
      );
  // Scope is evaluated per community: a referee in A is still a player in B.
  const isStaff = listWorkspaceIds.some((id) => hasWorkspacePermission(id, "match.result"));
  const [scope, setScope] = useState<ScrimListScope>("mine");
  const effectiveScope: ScrimListScope = isStaff ? scope : "mine";
  const roomsQueries = useQueries({
    queries: listWorkspaceIds.map((id) => {
      const localScope = hasWorkspacePermission(id, "match.result") ? scope : "mine";
      return {
        queryKey: [...scrimQueryKeys.list(id, localScope), user?.id],
        queryFn: () => scrimService.listRooms(id, localScope),
        enabled: Boolean(user)
      };
    })
  });
  const creationWorkspaces = accessibleWorkspaceIds.map((id) => ({
    id,
    name: workspaces.find((workspace) => workspace.id === id)?.name ?? t("list.communityId", { id })
  }));

  const closeMutation = useMutation({
    mutationFn: (token: string) => scrimService.closeRoom(token),
    onSuccess: async (room) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: scrimQueryKeys.lists(room.workspace_id) }),
        queryClient.invalidateQueries({ queryKey: scrimQueryKeys.room(room.token) })
      ]);
      notify.success(t("list.closedToast"));
    },
    onError: (error) => notify.error(getApiErrorMessage(error, t("list.closeFailed")))
  });

  const rooms = roomsQueries.flatMap((query) => query.data?.rooms ?? []).sort(
    (left, right) =>
      Number(left.closed_at != null) - Number(right.closed_at != null) || right.id - left.id
  );

  // One body per state, in priority order. `idle` counts as loading: the
  // profile fetch has not run yet, and flashing the sign-in card at an
  // authenticated captain is worse than a skeleton.
  const renderRooms = () => {
    if (status === "loading" || status === "idle") {
      return <Skeleton className="h-40 w-full rounded-xl" />;
    }
    if (!user) {
      return (
        <PageStateCard
          state="empty"
          title={t("signInTitle")}
          description={t("signInDescription")}
          actionLabel={t("signIn")}
          onAction={() => openAuthModal(getCurrentPathForAuthRedirect(window.location))}
        />
      );
    }
    if (!isAll && listWorkspaceIds.length === 0) {
      return (
        <PageStateCard
          state="empty"
          title={t("noWorkspaceTitle")}
          description={t("noWorkspaceDescription")}
        />
      );
    }
    if (roomsQueries.some((query) => query.isPending) || (isAll && workspacesLoading)) {
      return (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      );
    }
    if (roomsQueries.some((query) => query.isError)) {
      return (
        <PageStateCard
          state="error"
          actionLabel={t("list.retry")}
          onAction={() => void Promise.all(roomsQueries.map((query) => query.refetch()))}
        />
      );
    }
    if (rooms.length === 0) {
      return (
        <PageStateCard
          state="empty"
          title={
            effectiveScope === "workspace" ? t("list.emptyWorkspaceTitle") : t("list.emptyTitle")
          }
          description={
            effectiveScope === "workspace"
              ? t("list.emptyWorkspaceDescription")
              : t("list.emptyDescription")
          }
        />
      );
    }
    return (
      <div className="space-y-3">
        {rooms.map((room) => (
          <RoomCard
            key={room.id}
            room={room}
            communityName={isAll
              ? workspaces.find((workspace) => workspace.id === room.workspace_id)?.name
                ?? t("list.communityId", { id: room.workspace_id })
              : undefined}
            isClosing={closeMutation.isPending && closeMutation.variables === room.token}
            onClose={() => closeMutation.mutate(room.token)}
          />
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <PageHero
        eyebrow={<HeroCoord>{t("hero.eyebrow")}</HeroCoord>}
        title={t("hero.title")}
        lede={t("hero.lede")}
        actions={
          user && (isAll ? creationWorkspaces.length > 0 : listWorkspaceIds.length > 0) ? (
            <ScrimCreateDialog
              key={isAll ? "all" : hostLockedWorkspaceId ?? workspaceId}
              workspaceId={isAll ? null : hostLockedWorkspaceId ?? workspaceId}
              workspaces={creationWorkspaces}
            />
          ) : null
        }
      />

      {isStaff ? (
        <ToggleGroup
          type="single"
          variant="pill"
          value={scope}
          onValueChange={(next) => { if (next) setScope(next as ScrimListScope); }}
          aria-label={t("list.scopeLabel")}
        >
          <ToggleGroupItem value="mine">{t("list.scopeMine")}</ToggleGroupItem>
          <ToggleGroupItem value="workspace">{t("list.scopeWorkspace")}</ToggleGroupItem>
        </ToggleGroup>
      ) : null}

      {renderRooms()}

      <p className="text-muted-foreground flex items-center gap-2 text-xs">
        <Swords aria-hidden className="size-3.5" />
        {t("list.privacyNote")}
      </p>
    </div>
  );
}
