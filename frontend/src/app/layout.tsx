import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Barlow_Condensed, Onest } from "next/font/google";
import "./globals.css";
import React from "react";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-inter",
  display: "swap"
});

// Editorial Tactical display face (design-book): cyrillic-native geometric
// grotesk used for page-hero titles. Mixed-case, never condensed-caps.
const onest = Onest({
  subsets: ["latin", "cyrillic"],
  weight: ["500", "600", "700"],
  variable: "--font-onest",
  display: "swap"
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains-mono",
  display: "swap"
});

const barlowCondensed = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-barlow-condensed",
  display: "swap"
});
import { Providers } from "@/app/providers";
import { GoogleAnalytics } from "@next/third-parties/google";
import { cn } from "@/lib/utils";
import AuthModal from "@/components/AuthModal";
import AccountSettingsModal from "@/components/AccountSettingsModal";
import LoginModalTrigger from "@/components/LoginModalTrigger";
import { Toaster } from "@/components/ui/sonner";
import { Suspense } from "react";
import { resolveSiteMetadata } from "@/lib/site-metadata";

export async function generateMetadata(): Promise<Metadata> {
  const { name, description, origin, icon } = await resolveSiteMetadata();
  return {
    title: name,
    description,
    metadataBase: new URL(origin),
    icons: {
      icon
    },
    openGraph: {
      title: name,
      description,
      url: origin,
      type: "website",
      siteName: name,
      locale: "en_US"
    }
  };
}

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={cn(
          inter.className,
          inter.variable,
          jetbrainsMono.variable,
          barlowCondensed.variable,
          onest.variable,
          "dark"
        )}
      >
        <GoogleAnalytics gaId="G-6TYE0K6SQM" />
        <Providers>
          <Suspense fallback={null}>
            <LoginModalTrigger />
          </Suspense>
          <AuthModal />
          <Suspense fallback={null}>
            <AccountSettingsModal />
          </Suspense>
          <Toaster />
          {children}
        </Providers>
      </body>
    </html>
  );
}
