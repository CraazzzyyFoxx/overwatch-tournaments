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
import { OAUTH_PROVIDER_META } from "@/lib/oauth-providers";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { SITE_ICON, SITE_NAME } from "@/config/site";

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
      className="h-10 w-full justify-start bg-white/[0.04] border-white/[0.08] hover:bg-white/[0.08] hover:border-white/[0.16] transition-all duration-150 text-white/75 hover:text-white rounded-lg gap-3 font-normal"
    >
      <Link href={href}>
        <div className="flex h-4 w-4 shrink-0 items-center justify-center">
          {icon}
        </div>
        <span className="text-[13px] font-medium">{title}</span>
      </Link>
    </Button>
  );
};

const AuthModal = () => {
  const t = useTranslations();
  const isOpen = useAuthModalStore((state) => state.isOpen);
  const nextPath = useAuthModalStore((state) => state.nextPath);
  const close = useAuthModalStore((state) => state.close);
  const { data, isLoading } = useOAuthProviders();

  const next = encodeURIComponent(nextPath || "/");
  const providers = data?.map((item) => item.provider) ?? [];

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-[360px] p-0 overflow-hidden bg-[#111113] border-white/[0.08] shadow-2xl">
        {/* Branding header */}
        <div className="flex flex-col items-center px-8 pt-8 pb-6">
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] shadow-sm">
            <Image
              src={SITE_ICON}
              alt={SITE_NAME}
              width={22}
              height={22}
              className="rounded-sm"
            />
          </div>

          <DialogTitle className="text-[15px] font-semibold text-white tracking-[-0.01em]">
            {t("auth.signIn")}
          </DialogTitle>
          <DialogDescription className="mt-1 text-[12px] text-white/40 font-normal">
            {t("auth.continueTo", { siteName: SITE_NAME })}
          </DialogDescription>
        </div>

        {/* Divider */}
        <div className="h-px bg-white/[0.06]" />

        {/* Provider buttons */}
        <div className="px-8 py-5 grid gap-2">
          {isLoading
            ? ["discord", "twitch", "battlenet"].map((provider) => (
                <Skeleton key={provider} className="h-10 rounded-lg bg-white/[0.05]" />
              ))
            : providers.map((provider) => {
                const meta = OAUTH_PROVIDER_META[provider];

                return (
                  <ProviderButton
                    key={provider}
                    href={`/auth/${provider}/login?next=${next}`}
                    title={t("auth.continueWith", { provider: meta.title })}
                    icon={
                      <Image
                        src={meta.icon}
                        alt={meta.title}
                        width={16}
                        height={16}
                        className={provider === "battlenet" ? "brightness-125" : ""}
                      />
                    }
                  />
                );
              })}

          {!isLoading && providers.length === 0 && (
            <p className="text-[12px] text-white/30 text-center py-1">
              {t("auth.unavailable")}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="h-px bg-white/[0.06]" />
        <div className="px-8 py-4 flex justify-center">
          <p className="text-[11px] text-white/25 text-center leading-relaxed">
            {t.rich("auth.agreement", {
              terms: (chunks) => (
                <span className="text-white/40 underline underline-offset-2 decoration-white/20 cursor-pointer hover:text-white/60 transition-colors">
                  {chunks}
                </span>
              ),
              privacy: (chunks) => (
                <span className="text-white/40 underline underline-offset-2 decoration-white/20 cursor-pointer hover:text-white/60 transition-colors">
                  {chunks}
                </span>
              )
            })}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default AuthModal;
