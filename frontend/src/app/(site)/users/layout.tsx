import type { Metadata } from "next";
import React from "react";
import { SITE_NAME, SITE_URL, SITE_URL_OBJ } from "@/config/site";

export const metadata: Metadata = {
  title: `Users | ${SITE_NAME}`,
  description: `View users on ${SITE_NAME}.`,
  metadataBase: SITE_URL_OBJ,
  openGraph: {
    title: `Users | ${SITE_NAME}`,
    description: `View users on ${SITE_NAME}.`,
    url: SITE_URL,
    type: "website",
    siteName: SITE_URL,
    locale: "en_US"
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
