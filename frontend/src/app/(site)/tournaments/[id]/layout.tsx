import React, { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import TournamentClientLayout from "./_components/TournamentClientLayout";
import { TournamentShellSkeleton } from "./_components/TournamentSkeletons";
import { getTournamentOverview } from "./_data";
import TournamentOverviewBoundary from "./TournamentOverviewBoundary";
import { resolveSiteMetadata } from "@/lib/site-metadata";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const tournamentId = Number(params.id);
  const { name, origin } = await resolveSiteMetadata();
  const metadataBase = new URL(origin);
  const t = await getTranslations();

  try {
    const tournament = await getTournamentOverview(tournamentId);
    const title = `${t("tournamentDetail.metaTitle", { name: tournament.name })} | ${name}`;
    const description = t("tournamentDetail.metaDescription", {
      name: tournament.name,
    });

    return {
      title,
      description,
      metadataBase,
      openGraph: {
        title,
        description,
        url: `${origin}/tournaments/${tournamentId}`,
        type: "website",
        siteName: name,
        locale: "en_US"
      }
    };
  } catch {
    return {
      title: `${t("tournamentDetail.metaTitleFallback")} | ${name}`,
      description: t("tournamentDetail.metaDescriptionFallback"),
      metadataBase
    };
  }
}

export default async function TournamentLayout({
  children,
  params
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}>) {
  const resolvedParams = await params;
  const tournamentId = Number(resolvedParams.id);

  return (
    <Suspense fallback={<TournamentShellSkeleton />}>
      <TournamentOverviewBoundary tournamentId={tournamentId}>
        <TournamentClientLayout tournamentId={tournamentId}>
          {children}
        </TournamentClientLayout>
      </TournamentOverviewBoundary>
    </Suspense>
  );
}
