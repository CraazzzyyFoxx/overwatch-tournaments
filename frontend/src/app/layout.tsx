import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import React from "react";

// Self-hosted, not `next/font/google`.
//
// `next/font/google` downloads the font files from fonts.gstatic.com DURING
// THE BUILD, at URLs whose hashes Google rotates. A production build died on
// four of them returning 404 while the CSS that named them had just been
// fetched — the edge serving that build host was handing out a CSS generation
// whose files had already been purged. There is no retry or fallback for that:
// the build simply fails, after twenty minutes of image layers, on someone
// else's CDN. Vendored, the frontend build has no network dependency at all.
//
// The files are the upstream variable TTFs from github.com/google/fonts,
// subset to `latin` + Latin Extended-A + `cyrillic` and converted to woff2
// (see `fonts/README.md` for the exact command). One file per family replaces
// the eight-to-seventeen per-subset files Google served.
const inter = localFont({
  src: "./fonts/inter-variable.woff2",
  // The wght axis span, so the browser interpolates instead of synthesizing
  // bold. Inter also carries an `opsz` axis, left free for `font-optical-sizing`.
  weight: "100 900",
  variable: "--font-inter",
  display: "swap"
});

// Editorial Tactical display face (design-book): cyrillic-native geometric
// grotesk used for page-hero titles. Mixed-case, never condensed-caps.
const onest = localFont({
  src: "./fonts/onest-variable.woff2",
  weight: "100 900",
  variable: "--font-onest",
  display: "swap"
});

import { Providers } from "@/app/providers";
import { cn } from "@/lib/utils";
import AuthModal from "@/components/AuthModal";
import AccountSettingsModal from "@/components/AccountSettingsModal";
import LoginModalTrigger from "@/components/LoginModalTrigger";
import { Toaster } from "@/components/ui/sonner";
import { Suspense } from "react";
import { resolveSiteMetadata } from "@/lib/site-metadata";
import { resolveTenantWorkspace } from "@/lib/tenant-host";
import { COOKIE_CONSENT_COOKIE } from "@/lib/cookie-consent";
import { GA_ID, YM_ID } from "@/config/site";
import CookieConsent from "@/components/CookieConsent";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";
import { getLocale } from "next-intl/server";
import { cookies } from "next/headers";

export async function generateMetadata(): Promise<Metadata> {
  const [{ name, description, origin, icon }, locale] = await Promise.all([
    resolveSiteMetadata(),
    getLocale()
  ]);
  return {
    title: name,
    description,
    metadataBase: new URL(origin),
    icons: {
      icon,
      apple: "/apple-touch-icon.png"
    },
    openGraph: {
      title: name,
      description,
      url: origin,
      type: "website",
      siteName: name,
      locale: locale === "ru" ? "ru_RU" : "en_US"
    }
  };
}

export default async function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [locale, tenantWorkspace, cookieStore] = await Promise.all([
    getLocale(),
    resolveTenantWorkspace(),
    cookies()
  ]);
  // Analytics only loads for a visitor who accepted it; anything other than an
  // explicit decision leaves the notice to ask.
  const rawConsent = cookieStore.get(COOKIE_CONSENT_COOKIE)?.value;
  const cookieConsent =
    rawConsent === "accepted" || rawConsent === "declined" ? rawConsent : null;
  return (
    // The next/font `.variable` classes MUST sit on <html>, not <body>: they
    // define --font-inter/--font-onest, and globals.css aliases them from
    // `:root` (--aqt-data, --aqt-display, --aqt-onest). Custom properties are
    // substituted where they are *declared*, so a `:root` alias cannot read a
    // variable defined one level down on <body> — it resolves to nothing and
    // every display surface silently falls back to Inter.
    <html lang={locale} className={cn(inter.variable, onest.variable)}>
      <body className={cn(inter.className, "dark")}>
        <ZoneIntlProvider zone="root">
          <Providers>
            <Suspense fallback={null}>
              <LoginModalTrigger />
            </Suspense>
            <AuthModal tenantWorkspace={tenantWorkspace ?? undefined} />
            <Suspense fallback={null}>
              <AccountSettingsModal />
            </Suspense>
            <CookieConsent initial={cookieConsent} gaId={GA_ID} ymId={YM_ID} />
            <Toaster />
            {children}
          </Providers>
        </ZoneIntlProvider>
      </body>
    </html>
  );
}
