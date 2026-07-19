"use client";

import { useParams } from "next/navigation";

import { VetoRoom } from "./_components/VetoRoom";

export default function VetoRoomPage() {
  const params = useParams<{ id: string; encounterId: string }>();
  const encounterId = Number(params.encounterId);

  return <VetoRoom encounterId={encounterId} />;
}
