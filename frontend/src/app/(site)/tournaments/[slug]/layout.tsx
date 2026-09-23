import React, { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import TournamentClientLayout from "./_components/TournamentClientLayout";
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

  return (
    <>
      <Suspense fallback={null}>
        <TournamentOverviewBoundary slug={resolvedParams.slug} />
      </Suspense>
      <TournamentClientLayout slug={resolvedParams.slug}>{children}</TournamentClientLayout>
    </>
  );
}
