"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { tabFallback } from "../../hubQueries";
import { MatchesView } from "../MatchesView";

const PregameRoomsBrowser = dynamic(
  () =>
    import("@/components/admin/pregame-rooms/PregameRoomsBrowser").then((module) => ({
      default: module.PregameRoomsBrowser
    })),
  { loading: () => tabFallback }
);

export default function PregameRoomsViewPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);

  return (
    <MatchesView tournamentId={tournamentId}>
      {() => <PregameRoomsBrowser tournamentId={tournamentId} />}
    </MatchesView>
  );
}
