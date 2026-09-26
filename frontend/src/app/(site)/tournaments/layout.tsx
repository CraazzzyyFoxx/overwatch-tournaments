// The `.aqt-tn` shell stylesheet: this layout is the only place that mounts the
// scope root, so the rules ship with this route instead of with globals.css.
import "./tournaments.css";

import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "common.tournaments",
    descriptionKey: "tournamentsList.meta.description"
  });
}

export default function TournamentsLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
