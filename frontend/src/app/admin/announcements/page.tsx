"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AnnouncementForm } from "@/components/admin/announcements/AnnouncementForm";
import { AnnouncementsTable } from "@/components/admin/announcements/AnnouncementsTable";
import type { AnnouncementAudience } from "@/components/admin/announcements/announcement-draft";
import { AdminTabs } from "@/components/kit/AdminTabs";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notificationQueryKeys } from "@/lib/notification-query-keys";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AnnouncementCreateBody, NotificationItem } from "@/types/notification.types";

/** Same name the audit feed uses for the same question. */
const SCOPE_PARAM = "scope";

/**
 * Announcements an operator writes by hand — the only notification rows with
 * author-written text.
 *
 * The audience is one choice, not two: the list endpoint serves one scope at a
 * time (a workspace's rows, or the platform-wide ones), and a new announcement
 * belongs to the scope on screen. Splitting them into a filter and a form field
 * would let an operator read one feed while publishing into another.
 *
 * Both halves of that choice are gated the way the RPC gates them, so no offered
 * option can only end in a 403: `global` is the platform principal's
 * (`_authorize` requires a superuser — a workspace owner holding
 * `announcement.create` must not speak in the platform's voice), and `workspace`
 * needs the grant in *this* workspace. Reading and writing are separate grants,
 * so a `announcement.read` holder gets the table without the form.
 */
export default function AdminAnnouncementsPage() {
  const { isSuperuser, canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const t = useTranslations<never>();
  const queryClient = useQueryClient();
  const { searchParams } = useQueryParams({ resetOnChange: [] });

  // A fresh form after a successful publish: remounting is the whole reset.
  const [formGeneration, setFormGeneration] = useState(0);
  const [composerOpen, setComposerOpen] = useState(false);

  const canReadWorkspace = workspaceId != null && canAccessPermission("announcement.read", workspaceId);
  const audiences: AnnouncementAudience[] = [
    ...(canReadWorkspace ? (["workspace"] as const) : []),
    ...(isSuperuser ? (["global"] as const) : []),
  ];
  // The scope lives in the URL, not in component state: these are the screen's
  // own tabs, and `AdminTabs` renders real links — which is also what makes a
  // platform-wide feed linkable and survive a reload.
  const requested = searchParams?.get(SCOPE_PARAM);
  const audience =
    requested && audiences.includes(requested as AnnouncementAudience)
      ? (requested as AnnouncementAudience)
      : (audiences[0] ?? null);

  const scopeWorkspaceId = audience === "global" ? null : workspaceId;
  // Two grants, two questions: reading the feed, writing to it and taking a row
  // down are separate permissions server-side, so a `announcement.read` holder
  // gets the table with neither the form nor the Unpublish button.
  const canPublish =
    audience === "global"
      ? isSuperuser
      : audience === "workspace" && canAccessPermission("announcement.create", workspaceId);
  const canRetire =
    audience === "global"
      ? isSuperuser
      : audience === "workspace" && canAccessPermission("announcement.delete", workspaceId);

  const list = useQuery({
    queryKey: notificationQueryKeys.announcementsAdmin(scopeWorkspaceId),
    queryFn: () => notificationService.listAnnouncements({ workspaceId: scopeWorkspaceId }),
    enabled: audience !== null,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: notificationQueryKeys.announcementsAdmin(scopeWorkspaceId),
    });
    // The banner and the bell read the same rows, so a publish that does not
    // reach them is an announcement nobody sees until the next full reload.
    void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.activeAnnouncements() });
    void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.list() });
  };

  const create = useMutation({
    mutationFn: (body: AnnouncementCreateBody) => notificationService.createAnnouncement(body),
    onSuccess: () => {
      // Closing and remounting IS the reset: an announcement is written once
      // rather than edited into the next one.
      setComposerOpen(false);
      setFormGeneration((generation) => generation + 1);
      notify.success(t("notifications.admin.published"));
      invalidate();
    },
  });

  const retire = useMutation({
    mutationFn: (row: NotificationItem) => notificationService.retireAnnouncement(row.id),
    onSuccess: () => {
      notify.success(t("notifications.admin.retire.done"));
      invalidate();
    },
  });

  if (!isLoaded) return <Skeleton className="h-64 w-full rounded-xl" />;

  // Nothing picked and no platform scope to fall back on: there is no feed to
  // ask for yet, and "unauthorized" would be the wrong thing to say to someone
  // who has simply chosen no workspace.
  if (!isSuperuser && workspaceId == null) {
    return (
      <div className="space-y-6">
        <AdminPageHeader
          title={t("notifications.admin.title")}
          description={t("notifications.admin.description")}
        />
        <EmptyNote className="text-center">{t("notifications.admin.pickWorkspace")}</EmptyNote>
      </div>
    );
  }

  if (audience === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("notifications.admin.unauthorized.title")}</CardTitle>
          <CardDescription>{t("notifications.admin.unauthorized.description")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <AdminPageHeader
        title={t("notifications.admin.title")}
        description={t("notifications.admin.description")}
        actions={
          canPublish ? (
            <Button size="sm" data-field="compose" onClick={() => setComposerOpen(true)}>
              <Plus aria-hidden className="size-4" />
              {t("notifications.admin.form.title")}
            </Button>
          ) : undefined
        }
        /* Read and write are separate grants: without the second one the
           toolbar simply has no compose button, and this line is the only
           place that says why. */
        footer={
          canPublish ? undefined : (
            <p className="text-xs text-muted-foreground">{t("notifications.admin.readOnly")}</p>
          )
        }
      />

      {/* One row of tabs, the admin's own — the two feeds are two screens, not
          a filter over one. Rendered even at a single tab so the platform
          admin's row does not appear only after they gain the second scope. */}
      <div data-field="audience">
        <AdminTabs
          ariaLabel={t("notifications.admin.audienceLabel")}
          activeKey={audience}
          items={audiences.map((option) => ({
            key: option,
            label: t(`notifications.admin.audience.${option}`),
            href: `/admin/announcements?${SCOPE_PARAM}=${option}`,
          }))}
        />
      </div>

      <AnnouncementsTable
        rows={list.data ?? []}
        isLoading={list.isLoading}
        onRetire={canRetire ? (row) => retire.mutate(row) : undefined}
        isRetiring={retire.isPending}
      />

      {canPublish ? (
        <AnnouncementForm
          key={`${audience}-${formGeneration}`}
          open={composerOpen}
          onOpenChange={setComposerOpen}
          audience={audience}
          workspaceId={workspaceId}
          isPublishing={create.isPending}
          onPublish={(body) => create.mutate(body)}
        />
      ) : null}
    </div>
  );
}
