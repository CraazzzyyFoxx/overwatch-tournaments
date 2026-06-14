import React from "react";
import type { Metadata } from "next";

import TournamentClientLayout from "./_components/TournamentClientLayout";
import { getTournament } from "./_data";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const tournamentId = Number(params.id);

  try {
    const tournament = await getTournament(tournamentId);
    const title = `${tournament.name} | AQT`;

    return {
      title,
      description: `Overview for ${tournament.name} on AQT.`,
      openGraph: {
        title,
        description: `Overview for ${tournament.name} on AQT.`,
        url: `https://aqt.craazzzyyfoxx.me/tournaments/${tournamentId}`,
        type: "website",
        siteName: "AQT",
        locale: "en_US"
      }
    };
  } catch {
    return {
      title: "Tournament | AQT",
      description: "Tournament overview on AQT."
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
