import { redirect } from "next/navigation";

export default async function LegacyTournamentDraftRoute({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/draft/${id}`);
}
