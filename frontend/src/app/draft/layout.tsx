import type { ReactNode } from "react";

import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";

/**
 * The draft room's only reason to have a layout: it is the second half of the
 * `tools` zone, and a zone's message bundle is mounted by its layout. Reaching
 * /draft/x from a tournament page is a client-side navigation, which re-renders
 * nothing above this file — without it the room renders under whichever bundle
 * the first page load chose.
 */
export default function DraftLayout({ children }: Readonly<{ children: ReactNode }>) {
  return <ZoneIntlProvider zone="tools">{children}</ZoneIntlProvider>;
}
