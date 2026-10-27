"use client";

import { useTranslations } from "next-intl";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { TournamentsBrowser } from "@/components/admin/tournaments/list/TournamentsBrowser";

export default function TournamentsPage() {
  const t = useTranslations("adminTournaments.list");

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader title={t("title")} />
      <TournamentsBrowser />
    </div>
  );
}
