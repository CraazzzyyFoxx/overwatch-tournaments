"use client";

import Link from "next/link";
import Image from "next/image";
import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle
} from "@/components/ui/dialog";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOAuthProviders } from "@/hooks/use-oauth-providers";
import { getSocialProviderConfig } from "@/lib/social/providers";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { SITE_ICON, SITE_NAME } from "@/config/site";
import WorkspaceBrandIcon from "@/components/WorkspaceBrandIcon";
import type { TenantWorkspaceBranding } from "@/lib/site/tenant-host";

type ProviderButtonProps = {
  href: string;
  title: string;
  icon: ReactNode;
};

const ProviderButton = ({ href, title, icon }: ProviderButtonProps) => {
  return (
    <Button
      asChild
      variant="outline"
      className="h-10 w-full justify-start gap-3 rounded-lg border-border/70 bg-[color:var(--aqt-overlay-2)] font-normal text-[color:var(--aqt-fg-muted)] transition-all duration-150 hover:border-border hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
    >
      {/* Plain <a>, NEVER next/link: /auth/{provider}/login is a GET route
          handler with side effects — every execution mints a fresh OAuth state
          and overwrites the single shared owt_oauth_csrf cookie. <Link>
          prefetches it (on viewport entry AND hover), so late prefetch
          responses race the click's Set-Cookie and desync the cookie from the
          state carried to the provider, failing the callback's CSRF binding. */}
      <a href={href}>
        <div className="flex h-4 w-4 shrink-0 items-center justify-center">
          {icon}
        </div>
        <span className="text-caption font-medium">{title}</span>
      </a>
    </Button>
  );
};

type AuthModalProps = {
  /**
   * The host workspace's branding on a tenant (white-label) host, resolved
   * server-side in the root layout. When set, it replaces the platform
   * icon/name in the modal header. Absent on the apex/platform host.
   */
  tenantWorkspace?: TenantWorkspaceBranding;
};

const AuthModal = ({ tenantWorkspace }: AuthModalProps) => {
  const t = useTranslations();
  const isOpen = useAuthModalStore((state) => state.isOpen);
  const nextPath = useAuthModalStore((state) => state.nextPath);
  const close = useAuthModalStore((state) => state.close);
  const { data, isLoading } = useOAuthProviders(isOpen);

  const next = encodeURIComponent(nextPath || "/");
  const providers = data?.map((item) => item.provider) ?? [];
  const brandName = tenantWorkspace?.name ?? SITE_NAME;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && close()}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-[360px]">
        {/* Branding header */}
        <div className="flex flex-col items-center px-8 pb-6 pt-8">
          {/* WorkspaceBrandIcon/next-image are decorative (alt=""); the group
              carries the name so the branding is not silent. */}
          <div
            role="img"
            aria-label={brandName}
            className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-[color:var(--aqt-overlay-3)] shadow-sm"
          >
            {tenantWorkspace ? (
              <WorkspaceBrandIcon
                name={tenantWorkspace.name}
                iconUrl={tenantWorkspace.iconUrl}
                className="size-[22px] rounded-sm text-label"
              />
            ) : (
              <Image
                src={SITE_ICON}
                alt=""
                width={22}
                height={22}
                aria-hidden
                className="rounded-sm"
              />
            )}
          </div>

          <DialogTitle className="text-ui font-semibold tracking-[-0.01em] text-[color:var(--aqt-fg)]">
            {t("auth.signIn")}
          </DialogTitle>
          <DialogDescription className="mt-1 text-label font-normal text-[color:var(--aqt-fg-dim)]">
            {t("auth.continueTo", { siteName: brandName })}
          </DialogDescription>
        </div>

        {/* Divider */}
        <div className="h-px bg-border/70" />

        {/* Provider buttons */}
        <div className="grid gap-2 px-8 py-5">
          {isLoading
            ? ["discord", "twitch", "battlenet"].map((provider) => (
                <Skeleton key={provider} className="h-10 rounded-lg" />
              ))
            : providers.map((provider) => {
                const { label, icon } = getSocialProviderConfig(provider);

                return (
                  <ProviderButton
                    key={provider}
                    href={`/auth/${provider}/login?next=${next}`}
                    title={t("auth.continueWith", { provider: label })}
                    icon={
                      icon ? (
                        <Image
                          src={icon}
                          alt=""
                          width={16}
                          height={16}
                          aria-hidden
                          className={provider === "battlenet" ? "brightness-125" : ""}
                        />
                      ) : null
                    }
                  />
                );
              })}

          {!isLoading && providers.length === 0 && (
            <p className="py-1 text-center text-label text-[color:var(--aqt-fg-dim)]">
              {t("auth.unavailable")}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="h-px bg-border/70" />
        <div className="flex justify-center px-8 py-4">
          <p className="text-center text-label leading-relaxed text-[color:var(--aqt-fg-faint)]">
            {t.rich("auth.agreement", {
              terms: (chunks) => (
                <Link
                  href="/terms"
                  onClick={close}
                  className="font-medium text-[color:var(--aqt-fg-dim)] underline-offset-2 hover:underline"
                >
                  {chunks}
                </Link>
              ),
              privacy: (chunks) => (
                <Link
                  href="/privacy"
                  onClick={close}
                  className="font-medium text-[color:var(--aqt-fg-dim)] underline-offset-2 hover:underline"
                >
                  {chunks}
                </Link>
              )
            })}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default AuthModal;
