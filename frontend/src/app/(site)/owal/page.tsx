import React from "react";
import OwalSeasonFilter from "./components/OwalSeasonFilter";
import OwalPageTabs from "./components/OwalPageTabs";
import { getOwalPageData, OwalPageSearchParams } from "./_data";

export const dynamic = "force-dynamic";

type OwalPageProps = {
  searchParams: Promise<OwalPageSearchParams>;
};

const OwalPage = async ({ searchParams }: OwalPageProps) => {
  const { seasons, selectedSeason, standings, stacks } = await getOwalPageData(searchParams);

  return (
    <div className="flex flex-col gap-4">
      {selectedSeason ? <OwalSeasonFilter seasons={seasons} selectedSeason={selectedSeason} /> : null}
      <OwalPageTabs standings={standings} stacks={stacks} />
    </div>
  );
};

export default OwalPage;
