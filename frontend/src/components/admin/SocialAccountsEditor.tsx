"use client";

import { useId, useState, type FormEvent } from "react";
import { AlertTriangle, Check, MoreHorizontal, Plus, Star } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { invalidProps, settingErrorId } from "@/components/kit/SettingRow";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { SocialIcon } from "@/components/social/SocialIcon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import {
  getSocialProviderConfig,
  SOCIAL_PROVIDER_ORDER,
  socialAccountLabel,
  socialAccountsForProvider
} from "@/lib/social/providers";
import adminService from "@/services/admin.service";
import type { SocialAccount, SocialProvider, User } from "@/types/user.types";

interface SocialAccountsEditorProps {
  userId: number;
  accounts: SocialAccount[];
  /** Superuser: full add/edit/delete/set-primary management. */
  canManage: boolean;
  /** Read rights: toggle per-workspace / global display visibility. */
  canSetVisibility: boolean;
  /** Current workspace for the per-workspace visibility toggle (null = none). */
  workspaceId: number | null;
  onUserUpdated: (user: User) => void;
}

/** Where an account may be shown: the public profile (`null`) or one workspace. */
interface VisibilityScope {
  workspaceId: number | null;
  label: string;
}

// The switch columns line up under heads said once: every row and the head
// share these widths from `@lg` (32rem) of the editor's own width. Narrower —
// the 448px dialog, a phone — the heads go and each row labels its switches
// under the handle.
const SCOPE_CELL = "@lg:w-28 @lg:justify-center";
const MENU_CELL = "w-7 shrink-0";

// ─── Visibility switches (public profile + current workspace) ────────────────

function VisibilitySwitches({
  account,
  userId,
  scopes,
  onUserUpdated
}: Readonly<{
  account: SocialAccount;
  userId: number;
  scopes: VisibilityScope[];
  onUserUpdated: (user: User) => void;
}>) {
  const t = useTranslations("adminPeople.social");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (vars: { workspace_id: number | null; visible: boolean }) =>
      adminService.setSocialAccountVisibility(userId, account.id, vars),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });
      onUserUpdated(user);
    }
  });

  return (
    <div
      className="order-last flex basis-full flex-wrap items-center gap-x-4 gap-y-1 @lg:order-none @lg:basis-auto @lg:flex-nowrap @lg:gap-x-0"
      aria-busy={mutation.isPending}
    >
      {scopes.map((scope) => {
        const visible =
          scope.workspaceId === null
            ? (account.visible_global ?? true)
            : (account.visible_workspace_ids ?? []).includes(scope.workspaceId);
        return (
          <label
            key={scope.workspaceId ?? "public"}
            className={`flex cursor-pointer select-none items-center gap-2 ${SCOPE_CELL}`}
          >
            <Switch
              checked={visible}
              disabled={mutation.isPending}
              aria-label={t("visibility", { account: account.username, scope: scope.label })}
              onCheckedChange={(next) => mutation.mutate({ workspace_id: scope.workspaceId, visible: next })}
            />
            <span aria-hidden className="text-caption text-muted-foreground @lg:hidden">
              {scope.label}
            </span>
          </label>
        );
      })}
    </div>
  );
}

// ─── Single account row (view / inline edit) ─────────────────────────────────

function AccountRow({
  account,
  userId,
  canManage,
  scopes,
  onUserUpdated
}: Readonly<{
  account: SocialAccount;
  userId: number;
  canManage: boolean;
  scopes: VisibilityScope[];
  onUserUpdated: (user: User) => void;
}>) {
  const t = useTranslations("adminPeople.social");
  const tTable = useTranslations("kitTable.dataTableExtra");
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(account.username);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const config = getSocialProviderConfig(account.provider);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });

  const updateMutation = useMutation({
    mutationFn: (username: string) => adminService.updateSocialAccount(userId, account.id, { username }),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setEditing(false);
    }
  });
  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteSocialAccount(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
      setDeleteOpen(false);
    }
  });
  const primaryMutation = useMutation({
    mutationFn: () => adminService.setSocialAccountPrimary(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
    }
  });
  const verifyMutation = useMutation({
    mutationFn: () => adminService.verifySocialAccount(userId, account.id),
    onSuccess: (user) => {
      invalidate();
      onUserUpdated(user);
    },
    onError: (error) =>
      notify.apiError(error, { title: t("verifyFailed", { username: account.username }) })
  });

  if (editing) {
    const trimmed = editValue.trim();
    const save = (event: FormEvent) => {
      event.preventDefault();
      if (!trimmed || trimmed === account.username) {
        setEditing(false);
        return;
      }
      if (!updateMutation.isPending) updateMutation.mutate(trimmed);
    };
    return (
      <li className="py-2">
        <form onSubmit={save} className="flex items-center gap-2">
          <Input
            autoFocus
            size="sm"
            value={editValue}
            aria-label={t("handle", { provider: config.label })}
            readOnly={updateMutation.isPending}
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => setEditValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setEditing(false);
            }}
            className="min-w-0 flex-1"
          />
          <Button type="submit" size="sm" variant="outline" disabled={updateMutation.isPending || !trimmed}>
            {t("save")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={updateMutation.isPending}
            onClick={() => setEditing(false)}
          >
            {t("cancel")}
          </Button>
        </form>
      </li>
    );
  }

  const busy = verifyMutation.isPending || primaryMutation.isPending || deleteMutation.isPending;
  const canVerify = canManage && !account.is_verified && config.canBeVerified;
  const canMakePrimary = canManage && !account.is_primary;

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 @lg:flex-nowrap">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className="truncate text-body font-medium" title={account.username}>
          {socialAccountLabel(account)}
        </span>
        {account.display_name ? (
          <span className="shrink-0 text-caption text-muted-foreground tabular-nums">{account.username}</span>
        ) : null}
        {account.is_verified ? <StatusIcon icon={Check} label={t("verified")} variant="success" /> : null}
        {account.is_primary ? (
          <StatusIcon icon={Star} label={t("primary")} variant="warning" className="fill-current" />
        ) : null}
      </div>
      {scopes.length > 0 ? (
        <VisibilitySwitches account={account} userId={userId} scopes={scopes} onUserUpdated={onUserUpdated} />
      ) : null}
      {canManage ? (
        <DropdownMenu>
          <DropdownMenuTrigger
            disabled={busy}
            aria-busy={busy}
            aria-label={tTable("actionsFor", { label: account.username })}
            title={tTable("actionsFor", { label: account.username })}
            className={`${MENU_CELL} inline-flex h-7 items-center justify-center rounded-md text-muted-foreground transition-[color,background-color] hover:bg-accent/40 hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50`}
          >
            <MoreHorizontal aria-hidden className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {canVerify ? (
              <DropdownMenuItem title={t("verifyTitle")} onSelect={() => verifyMutation.mutate()}>
                {t("verify")}
              </DropdownMenuItem>
            ) : null}
            {canMakePrimary ? (
              <DropdownMenuItem onSelect={() => primaryMutation.mutate()}>{t("makePrimary")}</DropdownMenuItem>
            ) : null}
            <DropdownMenuItem
              onSelect={() => {
                setEditValue(account.username);
                setEditing(true);
              }}
            >
              {t("edit")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDeleteOpen(true)} variant="destructive">
              {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: t("removeTitle", { username: account.username }),
          description: t("removeDescription", { provider: config.label, username: account.username }),
          confirmLabel: deleteMutation.isPending ? t("deleting") : t("deleteAction"),
          tone: "danger"
        }}
      />
    </li>
  );
}

// ─── Add at the list's foot ──────────────────────────────────────────────────

/** Pick a provider, type a handle, Enter. The field stays focused for the next one. */
function AddAccount({ userId, onUserUpdated }: Readonly<{ userId: number; onUserUpdated: (user: User) => void }>) {
  const t = useTranslations("adminPeople.social");
  const queryClient = useQueryClient();
  const inputId = useId();
  const [provider, setProvider] = useState<SocialProvider>(SOCIAL_PROVIDER_ORDER[0]);
  const [handle, setHandle] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const config = getSocialProviderConfig(provider);

  const add = useMutation({
    // The refusal is shown under the field; a toast would say it twice.
    meta: { suppressErrorToast: true },
    mutationFn: (username: string) => adminService.addSocialAccount(userId, { provider, username }),
    onSuccess: (user) => {
      setHandle("");
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });
      onUserUpdated(user);
    },
    onError: (error) => setRefusal(getApiErrorMessage(error, t("addError")))
  });
  const value = handle.trim();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value && !add.isPending) add.mutate(value);
  };

  return (
    <form onSubmit={submit} className="border-t border-border/60 pt-2.5">
      <div className="flex items-center gap-2">
        <Plus aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <Select
          value={provider}
          onValueChange={(next) => {
            setProvider(next as SocialProvider);
            setRefusal(null);
          }}
        >
          <SelectTrigger size="sm" className="w-36 shrink-0" aria-label={t("provider")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOCIAL_PROVIDER_ORDER.map((option) => (
              <SelectItem key={option} value={option}>
                <span className="flex items-center gap-2">
                  <SocialIcon provider={option} size={14} decorative />
                  {getSocialProviderConfig(option).label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          id={inputId}
          size="sm"
          value={handle}
          placeholder={config.placeholder}
          aria-label={t("handle", { provider: config.label })}
          // Read-only, not disabled: a disabled field drops focus, and the next handle is typed right after.
          readOnly={add.isPending}
          onChange={(event) => {
            setHandle(event.target.value);
            setRefusal(null);
          }}
          className="min-w-0 flex-1"
          {...invalidProps(inputId, refusal ?? undefined)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={!value || add.isPending}>
          {t("add")}
        </Button>
      </div>
      {refusal ? (
        <p
          id={settingErrorId(inputId)}
          role="alert"
          className="mt-1.5 flex items-start gap-1.5 text-caption text-danger"
        >
          <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {refusal}
        </p>
      ) : null}
    </form>
  );
}

// ─── Editor ──────────────────────────────────────────────────────────────────

/**
 * Every linked account at once, grouped by provider. A provider picker used to
 * show one provider at a time, which hid the Steam account Deadlock collects
 * from behind the Battle.net list. Superusers manage accounts; readers may
 * toggle where each one is shown.
 */
export function SocialAccountsEditor({
  userId,
  accounts,
  canManage,
  canSetVisibility,
  workspaceId,
  onUserUpdated
}: Readonly<SocialAccountsEditorProps>) {
  const t = useTranslations("adminPeople.social");
  const groups = SOCIAL_PROVIDER_ORDER.map((provider) => ({
    provider,
    items: socialAccountsForProvider(accounts, provider)
  })).filter((group) => group.items.length > 0);
  const scopes: VisibilityScope[] =
    canManage || canSetVisibility
      ? [
          { workspaceId: null, label: t("profile") },
          ...(workspaceId != null ? [{ workspaceId, label: t("workspace") }] : [])
        ]
      : [];

  return (
    <div className="@container space-y-4">
      {groups.length === 0 ? (
        <EmptyNote size="sm">{t("noIdentities")}</EmptyNote>
      ) : (
        groups.map((group, index) => (
          <div key={group.provider}>
            <div className="flex items-end gap-x-3">
              <h3 className={`${eyebrowClass("muted")} flex min-w-0 flex-1 items-center gap-1.5`}>
                <SocialIcon provider={group.provider} size={14} decorative />
                {getSocialProviderConfig(group.provider).label}
              </h3>
              {/* The switch heads, once, on the first group's line. Each switch
                  names its own account and scope, so these stay visual. */}
              {index === 0 && scopes.length > 0 ? (
                <div aria-hidden className="hidden @lg:flex">
                  {scopes.map((scope) => (
                    <span
                      key={scope.workspaceId ?? "public"}
                      className={`${eyebrowClass("muted")} ${SCOPE_CELL} flex text-center`}
                    >
                      {scope.label}
                    </span>
                  ))}
                  {canManage ? <span className={`${MENU_CELL} ml-3`} /> : null}
                </div>
              ) : null}
            </div>
            <ul className="divide-y divide-border/60">
              {group.items.map((account) => (
                <AccountRow
                  key={account.id}
                  account={account}
                  userId={userId}
                  canManage={canManage}
                  scopes={scopes}
                  onUserUpdated={onUserUpdated}
                />
              ))}
            </ul>
          </div>
        ))
      )}

      {canManage ? <AddAccount userId={userId} onUserUpdated={onUserUpdated} /> : null}
    </div>
  );
}
