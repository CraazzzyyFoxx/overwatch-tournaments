import type { Metadata } from "next";
import React from "react";
import { SITE_NAME } from "@/config/site";

export const metadata: Metadata = {
  title: `Teams | ${SITE_NAME}`,
  description: `View teams on ${SITE_NAME}.`,
  metadataBase: new URL("https://aqt.craazzzyyfoxx.me"),
  openGraph: {
    title: `Teams | ${SITE_NAME}`,
    description: `View teams on ${SITE_NAME}.`,
    url: "https://aqt.craazzzyyfoxx.me",
    type: "website",
    siteName: SITE_NAME,
    locale: "en_US"
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
