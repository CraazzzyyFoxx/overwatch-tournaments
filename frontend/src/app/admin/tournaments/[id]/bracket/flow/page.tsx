"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { tabFallback } from "../../hubQueries";

const FlowEditor = dynamic(() => import("./FlowEditor").then((module) => module.FlowEditor), {
  ssr: false,
  loading: () => tabFallback
});

export default function FlowTabPage() {
  const params = useParams<{ id: string }>();
  return <FlowEditor tournamentId={Number(params.id)} />;
}
