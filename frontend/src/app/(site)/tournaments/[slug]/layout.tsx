import React, { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import TournamentClientLayout from "./_components/TournamentClientLayout";
import { TournamentShellSkeleton } from "./_components/TournamentSkeletons";
import { getTournamentOverviewState } from "./_data";
import TournamentOverviewBoundary from "./TournamentOverviewBoundary";
import { resolveSiteMetadata } from "@/lib/site/metadata";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const { name, origin } = await resolveSiteMetadata();
  const metadataBase = new URL(origin);
  const t = await getTranslations();

  const overviewState = await getTournamentOverviewState(params.slug);
  if (overviewState.kind === "success") {
    const tournament = overviewState.overview;
    const title = `${t("tournamentDetail.metaTitle", { name: tournament.name })} | ${name}`;
    const description = t("tournamentDetail.metaDescription", {
      name: tournament.name
    });

    return {
      title,
      description,
      metadataBase,
      openGraph: {
        title,
        description,
        url: `${origin}/tournaments/${tournament.slug}`,
        type: "website",
        siteName: name,
        locale: "en_US"
      }
    };
  }

  return {
    title: `${t("tournamentDetail.metaTitleFallback")} | ${name}`,
    description: t("tournamentDetail.metaDescriptionFallback"),
    metadataBase
  };
}

export default async function TournamentLayout({
  children,
  params
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}>) {
  const resolvedParams = await params;

  // `TournamentOverviewBoundary` seeds the request's query cache and
  // `TournamentClientLayout` reads it — so the seed has to render FIRST, on the
  // server AND in the browser. That only holds while both sit inside the SAME
  // Suspense boundary: React hydrates a boundary's children as one unit, but a
  // sibling OUTSIDE the boundary hydrates in the first pass, before the
  // boundary's content exists on the client at all. With the shell outside, the
  // server rendered it from a warm cache and the browser re-rendered it from an
  // empty one — a guaranteed hydration mismatch that threw the whole shell away
  // and replayed it client-side on every load.
  //
  // Being inside the boundary costs the shell nothing it used to have: it
  // cannot render before the overview resolves anyway, and neither can the tab
  // below it (`TournamentTabBoundary` awaits the same request-cached read), so
  // the fallback is the only thing that could ever paint first. It is the same
  // skeleton the shell itself used to render while pending, and the same one
  // `loading.tsx` shows — now streamed from the server instead of appearing
  // after hydration.
  return (
    <Suspense fallback={<TournamentShellSkeleton />}>
      <TournamentOverviewBoundary slug={resolvedParams.slug} />
      <TournamentClientLayout slug={resolvedParams.slug}>{children}</TournamentClientLayout>
    </Suspense>
  );
}
