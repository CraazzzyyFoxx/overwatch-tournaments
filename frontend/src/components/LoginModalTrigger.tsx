"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { getSocialProviderConfig } from "@/lib/social/providers";
import { notify } from "@/lib/notify";
import { useAuthModalStore } from "@/stores/auth-modal.store";

// Error codes the auth routes redirect with in `?auth_error=` — see
// /auth/{provider}/login (oauth_init_failed), oauth-callback.ts, /auth/sso
// and /auth/link/complete. Anything unrecognized falls back to the generic
// message so future codes are never silently dropped again.
const KNOWN_AUTH_ERRORS: Record<string, true> = {
  oauth_init_failed: true,
  invalid_state: true,
  invalid_provider: true,
  exchange_failed: true,
  invalid_origin: true,
  // Account linking (oauth-callback.ts's "link" branch, /auth/link/complete):
  // this provider account already belongs to a different account here.
  link_taken: true
};

const LoginModalTrigger = () => {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("auth.errors");
  const tLink = useTranslations("auth.link");
  const open = useAuthModalStore((state) => state.open);

  const loginParam = searchParams.get("login");
  const nextParam = searchParams.get("next") ?? "/";
  const authError = searchParams.get("auth_error");
  const authErrorDescription = searchParams.get("auth_error_description");
  const authErrorProvider = searchParams.get("auth_error_provider");
  const authLink = searchParams.get("auth_link");
  const authLinkProvider = searchParams.get("auth_link_provider");

  useEffect(() => {
    if (loginParam === "1") {
      open(nextParam);
    }
  }, [loginParam, nextParam, open]);

  useEffect(() => {
    if (!authError) {
      return;
    }

    const key = KNOWN_AUTH_ERRORS[authError] ? authError : "generic";
    // Only the apex link callback knows which provider was being linked; the
    // custom-domain one sees an opaque ticket, hence the generic fallback.
    const provider = authErrorProvider
      ? getSocialProviderConfig(authErrorProvider).label
      : t("linkProviderFallback");
    // Fixed id: StrictMode double-runs effects in dev — the second toast
    // replaces the first instead of stacking a duplicate.
    notify.error(t(key as "generic", { provider }), {
      id: "auth-error",
      description: authErrorDescription ?? undefined
    });

    // Strip the error params so a refresh or back-navigation doesn't re-toast.
    const params = new URLSearchParams(searchParams);
    params.delete("auth_error");
    params.delete("auth_error_description");
    params.delete("auth_error_provider");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [authError, authErrorDescription, authErrorProvider, pathname, router, searchParams, t]);

  // Successful OAuth link (oauth-callback.ts / /auth/link/complete): always
  // confirm it, including a re-link of an account the user already had.
  useEffect(() => {
    if (authLink !== "linked" && authLink !== "already_linked") {
      return;
    }

    const provider = authLinkProvider
      ? getSocialProviderConfig(authLinkProvider).label
      : t("linkProviderFallback");
    notify.success(tLink(authLink, { provider }), { id: "auth-link" });

    const params = new URLSearchParams(searchParams);
    params.delete("auth_link");
    params.delete("auth_link_provider");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [authLink, authLinkProvider, pathname, router, searchParams, t, tLink]);

  return null;
};

export default LoginModalTrigger;
