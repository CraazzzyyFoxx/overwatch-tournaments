"use client";

import { useState } from "react";
import Image from "next/image";
import { ColumnDef } from "@tanstack/react-table";
import { ExternalLink, Globe, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { OAuthConnectionAdmin, OAuthProvider } from "@/types/rbac.types";

const PAGE_SIZE = 20;

const PROVIDER_META: Record<
  OAuthProvider,
  { label: string; icon: string | null; iconClass?: string }
> = {
  discord: { label: "Discord", icon: "/discord.png" },
  twitch: { label: "Twitch", icon: "/twitch.png" },
  battlenet: { label: "Battle.net", icon: "/battlenet.svg", iconClass: "invert grayscale" },
  google: { label: "Google", icon: null },
  github: { label: "GitHub", icon: null }
};

const PROVIDER_COLORS: Record<OAuthProvider, string> = {
  discord: "bg-[#5865F2]/15 text-[#7289da] border-[#5865F2]/30",
  twitch: "bg-[#9146FF]/15 text-[#b380ff] border-[#9146FF]/30",
  battlenet: "bg-[#148EFF]/15 text-[#60b0ff] border-[#148EFF]/30",
  google: "bg-red-500/15 text-red-400 border-red-500/30",
  github: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30"
};

function ProviderBadge({ provider }: { provider: OAuthProvider }) {
  const meta = PROVIDER_META[provider];
  return (
    <Badge variant="outline" className={`gap-1.5 ${PROVIDER_COLORS[provider]}`}>
      {meta?.icon ? (
        <Image
          src={meta.icon}
          alt={meta.label}
          width={14}
          height={14}
          className={meta.iconClass ?? ""}
        />
      ) : (
        <Globe className="h-3.5 w-3.5" />
      )}
      {meta?.label ?? provider}
    </Badge>
  );
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

function isTokenExpired(expiresAt: string | null | undefined): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

export default function OAuthConnectionsAdminPage() {
  const queryClient = useQueryClient();
  const { hasPermission } = usePermissions();
  const canDeleteConnections = hasPermission("auth_user.update");
  const [providerFilter, setProviderFilter] = useState<string>("all");
  const [deletingConnection, setDeletingConnection] = useState<OAuthConnectionAdmin | null>(null);

  const deleteConnectionMutation = useMutation({
    mutationFn: (connectionId: number) => rbacService.deleteOAuthConnection(connectionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["access-admin", "oauth-connections"] });
      setDeletingConnection(null);
      notify.success("OAuth connection removed");
    }
  });

  const columns: ColumnDef<OAuthConnectionAdmin>[] = [
    {
      accessorKey: "provider",
      header: "Provider",
      cell: ({ row }) => <ProviderBadge provider={row.original.provider} />
    },
    {
      id: "provider_user",
      header: "Provider Account",
      cell: ({ row }) => {
        const conn = row.original;
        return (
          <div className="flex items-center gap-3">
            <Avatar className="h-8 w-8">
              <AvatarImage src={conn.avatar_url ?? undefined} alt={conn.username} />
              <AvatarFallback className="text-xs">
                {conn.username.slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{conn.display_name ?? conn.username}</p>
              <p className="truncate text-xs text-muted-foreground">
                {conn.username}
                {conn.email ? ` \u00B7 ${conn.email}` : ""}
              </p>
            </div>
          </div>
        );
      }
    },
    {
      accessorKey: "provider_user_id",
      header: "Provider ID",
      cell: ({ row }) => (
        <code className="text-xs text-muted-foreground">{row.original.provider_user_id}</code>
      )
    },
    {
      id: "auth_user",
      header: "Auth User",
      cell: ({ row }) => {
        const conn = row.original;
        return (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="truncate text-sm font-medium">{conn.auth_user_username}</p>
              <a
                href={`/admin/access/users`}
                className="text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            <p className="truncate text-xs text-muted-foreground">{conn.auth_user_email}</p>
          </div>
        );
      }
    },
    {
      id: "token_status",
      header: "Token",
      cell: ({ row }) => {
        const expiresAt = row.original.token_expires_at;
        if (!expiresAt) {
          return <span className="text-xs text-muted-foreground">No token</span>;
        }
        const expired = isTokenExpired(expiresAt);
        return (
          <Badge
            variant="outline"
            className={
              expired ? "border-red-500/30 text-red-400" : "border-green-500/30 text-green-400"
            }
          >
            {expired ? "Expired" : "Active"}
          </Badge>
        );
      }
    },
    {
      accessorKey: "created_at",
      header: "Connected",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{formatDate(row.original.created_at)}</span>
      )
    },
    ...(canDeleteConnections
      ? ([
          {
            id: "actions",
            header: "",
            cell: ({ row }) => (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${row.original.provider} connection for ${row.original.username}`}
                onClick={() => setDeletingConnection(row.original)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )
          }
        ] satisfies ColumnDef<OAuthConnectionAdmin>[])
      : [])
  ];

  return (
    <>
      <div className="space-y-6">
        <AdminPageHeader
          title="OAuth Connections"
          description="View all OAuth provider connections linked to user accounts."
          meta={<Badge variant="secondary">Auth</Badge>}
        />

        <div className="flex items-center gap-4">
          <Select value={providerFilter} onValueChange={setProviderFilter}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Filter by provider" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Providers</SelectItem>
              {(
                Object.entries(PROVIDER_META) as [
                  OAuthProvider,
                  (typeof PROVIDER_META)[OAuthProvider]
                ][]
              ).map(([key, meta]) => (
                <SelectItem key={key} value={key}>
                  <span className="flex items-center gap-2">
                    {meta.icon ? (
                      <Image
                        src={meta.icon}
                        alt={meta.label}
                        width={14}
                        height={14}
                        className={meta.iconClass ?? ""}
                      />
                    ) : (
                      <Globe className="h-3.5 w-3.5" />
                    )}
                    {meta.label}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <AdminDataTable
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "access-admin",
            "oauth-connections",
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            providerFilter
          ]}
          queryFn={(page, search, pageSize, sortField, sortDir) =>
            rbacService.listOAuthConnections({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              provider: providerFilter !== "all" ? providerFilter : undefined
            })
          }
          columns={columns}
          searchPlaceholder="Search by username, email, or provider ID..."
          emptyMessage="No OAuth connections found."
        />
      </div>

      {deletingConnection ? (
        <DeleteConfirmDialog
          open={!!deletingConnection}
          onOpenChange={(open) => !open && setDeletingConnection(null)}
          onConfirm={() => deleteConnectionMutation.mutate(deletingConnection.id)}
          isDeleting={deleteConnectionMutation.isPending}
          title={`Remove ${PROVIDER_META[deletingConnection.provider]?.label ?? deletingConnection.provider} link?`}
          description={`This will detach ${deletingConnection.display_name ?? deletingConnection.username} from auth user ${deletingConnection.auth_user_username ?? `#${deletingConnection.auth_user_id}`}.`}
        />
      ) : null}
    </>
  );
}
