import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { pickMessages, type Zone } from "./zones";

/**
 * The client message bundle for one zone, mounted by that zone's layout.
 *
 * Nesting is deliberate: the root layout mounts `zone="root"` for the chrome it
 * renders outside `{children}` (auth modal, account settings, cookie notice,
 * toaster), and each zone layout mounts its own inside. `use-intl`'s
 * `IntlProvider` REPLACES `messages` rather than merging with the parent
 * (`messages: undefined === i ? parent?.messages : i`), which is why every zone
 * bundle is generated as a superset of the root one.
 */
export default async function ZoneIntlProvider({
  zone,
  children,
}: Readonly<{ zone: Zone; children: ReactNode }>) {
  return (
    <NextIntlClientProvider messages={pickMessages(await getMessages(), zone)}>
      {children}
    </NextIntlClientProvider>
  );
}
