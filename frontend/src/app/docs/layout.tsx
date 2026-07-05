import type { Metadata } from "next";
import React from "react";

// Self-contained developer-docs section: intentionally NOT wrapped in the public
// (site) chrome (Header/Footer). It inherits only the root <html>/<body> shell.
export const metadata: Metadata = {
  title: "Схема БД · anak-tournaments",
  description: "In-app ERD explorer for the anak-tournaments PostgreSQL schema.",
  robots: { index: false, follow: false }
};

export default function DocsLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <>{children}</>;
}
