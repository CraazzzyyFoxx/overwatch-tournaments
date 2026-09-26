import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

// A room is reached only by its shared token link: nothing here should be
// indexed, and the token must not end up in a search result.
export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "scrims.meta.room.title",
    descriptionKey: "scrims.meta.room.description",
    noIndex: true
  });
}

export default function ScrimRoomLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
