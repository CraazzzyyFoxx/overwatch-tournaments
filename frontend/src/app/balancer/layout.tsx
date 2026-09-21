import type { ReactNode } from "react";

import { BalancerLayoutClient } from "@/app/balancer/BalancerLayoutClient";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";

type BalancerLayoutProps = {
  children: ReactNode;
};

export default function BalancerLayout({ children }: Readonly<BalancerLayoutProps>) {
  return (
    <ZoneIntlProvider zone="tools">
      <BalancerLayoutClient>{children}</BalancerLayoutClient>
    </ZoneIntlProvider>
  );
}
