"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Check, Eye, EyeOff, Loader2, Plus, Star, Trash2 } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, sortSocialAccounts } from "@/lib/social-providers";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { usePermissions } from "@/hooks/usePermissions";
import meService from "@/services/me.service";
import type { User } from "@/types/user.types";

// Providers a user can OAuth-link (and thereby verify).
const OAUTH_ADDABLE = ["battlenet", "discord", "twitch"] as const;

export default function MyAccountSection() {
  const user = useAuthProfileStore((s) => s.user);
  const fetchMe = useAuthProfileStore((s) => s.fetchMe);
  const { canUseCapability } = usePermissions();
  const canAvatar = canUseCapability("account.avatar");
  const canSocial = canUseCapability("account.social");
  const fileRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const socialQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: canSocial,
  });
  const accounts = sortSocialAccounts(socialQuery.data?.social_accounts ?? []);

  const writeSocial = (user: User) => queryClient.setQueryData(["me", "social"], user);

  const avatarUpload = useMutation({
    mutationFn: (file: File) => meService.setAvatar(file),
    onSuccess: () => fetchMe({ force: true }),
  });
  const avatarDelete = useMutation({
    mutationFn: () => meService.deleteAvatar(),
    onSuccess: () => fetchMe({ force: true }),
  });
  const setPrimary = useMutation({
    mutationFn: (id: number) => meService.setSocialPrimary(id),
    onSuccess: writeSocial,
  });
  const setVisibility = useMutation({
    mutationFn: ({ id, visible }: { id: number; visible: boolean }) =>
      meService.setSocialVisibility(id, visible),
    onSuccess: writeSocial,
  });

  const linkHref = (provider: string) => {
    const next =
      typeof window !== "undefined" ? `${window.location.pathname}?settings=profile` : "/?settings=profile";
    return `/auth/${provider}/login?action=link&next=${encodeURIComponent(next)}`;
  };

  return (
    <div className="space-y-8">
      {/* ── Avatar ─────────────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-slate-300">Avatar</h4>
        <div className="flex items-center gap-4">
          <Avatar className="h-16 w-16">
            <AvatarImage src={user?.avatarUrl ?? undefined} alt={user?.username} />
            <AvatarFallback>{user?.username?.[0]?.toUpperCase() ?? "?"}</AvatarFallback>
          </Avatar>
          {canAvatar ? (
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) avatarUpload.mutate(file);
                  e.target.value = "";
                }}
              />
              <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} disabled={avatarUpload.isPending}>
                {avatarUpload.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Camera className="mr-2 h-4 w-4" />}
                Upload
              </Button>
              {user?.avatarUrl && (
                <Button size="sm" variant="ghost" onClick={() => avatarDelete.mutate()} disabled={avatarDelete.isPending}>
                  <Trash2 className="mr-2 h-4 w-4" /> Remove
                </Button>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500">Changing your avatar has been disabled by an administrator.</p>
          )}
        </div>
      </section>

      {/* ── Linked accounts ────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-slate-300">Linked accounts</h4>
        {!canSocial ? (
          <p className="text-xs text-slate-500">Managing your accounts has been disabled by an administrator.</p>
        ) : (
          <>
            <div className="space-y-1.5">
              {socialQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
              {!socialQuery.isLoading && accounts.length === 0 && (
                <p className="text-sm text-slate-500">No linked accounts yet — add one via OAuth below.</p>
              )}
              {accounts.map((account) => {
                const visible = account.visible_global !== false;
                return (
                  <div
                    key={account.id}
                    className={`flex items-center gap-2 rounded-lg border border-white/5 bg-white/3 px-3 py-2 ${visible ? "" : "opacity-50"}`}
                  >
                    <SocialIcon provider={account.provider} size={15} />
                    <span className="flex-1 truncate text-sm text-white">{account.username}</span>
                    {account.is_verified && <Check className="h-3.5 w-3.5 text-emerald-400" aria-label="Verified" />}
                    {account.is_primary ? (
                      <Star className="h-4 w-4 shrink-0 fill-amber-400 text-amber-400" aria-label="Primary" />
                    ) : (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        title={account.is_verified ? "Make primary" : "Only OAuth-verified accounts can be primary"}
                        disabled={!account.is_verified || setPrimary.isPending}
                        onClick={() => setPrimary.mutate(account.id)}
                      >
                        <Star className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-slate-400 hover:text-white"
                      title={visible ? "Hide from your public profile" : "Show on your public profile"}
                      disabled={setVisibility.isPending}
                      onClick={() => setVisibility.mutate({ id: account.id, visible: !visible })}
                      aria-label={`${visible ? "Hide" : "Show"} ${account.username}`}
                    >
                      {visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {OAUTH_ADDABLE.map((provider) => (
                <a
                  key={provider}
                  href={linkHref(provider)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white transition-colors hover:bg-white/10"
                >
                  <Plus className="h-3 w-3" />
                  <SocialIcon provider={provider} size={13} />
                  {getSocialProviderConfig(provider).label}
                </a>
              ))}
            </div>
            <p className="text-[11px] text-slate-500">
              Accounts can only be added through OAuth, which also verifies them. Hiding removes an account from
              your public profile; only an administrator can fully delete it.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
