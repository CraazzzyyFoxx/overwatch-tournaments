import React from "react";
import type { Metadata } from "next";

import TournamentClientLayout from "./_components/TournamentClientLayout";
import { getTournament } from "./_data";
import { resolveSiteMetadata } from "@/lib/site-metadata";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const tournamentId = Number(params.id);
  const { name, origin } = await resolveSiteMetadata();
  const metadataBase = new URL(origin);

  try {
    const tournament = await getTournament(tournamentId);
    const title = `${tournament.name} | AQT`;
    const description = `Overview for ${tournament.name} on AQT.`;

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
      title: "Tournament | AQT",
      description: "Tournament overview on AQT.",
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
    <TournamentClientLayout tournamentId={tournamentId}>
      {children}
    </TournamentClientLayout>
  );
}
