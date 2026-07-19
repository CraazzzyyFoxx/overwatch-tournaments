"use client";

import { useState } from "react";

import { RankHealthDashboard } from "./_components/rank-health";
import { RankPlayerDetail, RankPlayerSearch } from "./_components/rank-player";
import { RankTaskHistory } from "./_components/rank-task-history";

interface SelectedPlayer {
  userId: number;
  label: string;
}

export default function RankCollectionAdminPage() {
  const [selected, setSelected] = useState<SelectedPlayer | null>(null);
  const openPlayer = (userId: number, label: string) => setSelected({ userId, label });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">Rank Collection</h1>
          <p className="mt-2 text-muted-foreground">
            OverFast collection health, live worker task history and per-player inspection.
          </p>
        </div>
        <div className="sm:pt-1">
          <RankPlayerSearch onSelect={openPlayer} />
        </div>
      </div>

      <RankHealthDashboard />
      <RankTaskHistory onSelectUser={openPlayer} />

      {selected && (
        <RankPlayerDetail userId={selected.userId} label={selected.label} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
