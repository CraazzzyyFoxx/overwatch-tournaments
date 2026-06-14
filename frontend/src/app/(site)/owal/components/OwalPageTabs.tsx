import React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import OwalStandingsTable from "@/app/(site)/owal/components/OwalStandingsTable";
import OwalStacksTable from "./OwalStacksTable";
import { OwalStack, OwalStandings } from "@/types/tournament.types";

type OwalPageTabsProps = {
  standings: OwalStandings;
  stacks: OwalStack[];
};

const OwalPageTabs = ({ standings, stacks }: OwalPageTabsProps) => {
  return (
    <Tabs defaultValue="standings">
      <TabsList className="mb-4 grid w-[400px] grid-cols-2">
        <TabsTrigger value="standings">Standings</TabsTrigger>
        <TabsTrigger value="stacks">Stacks</TabsTrigger>
      </TabsList>
      <TabsContent value="standings">
        <OwalStandingsTable data={standings} />
      </TabsContent>
      <TabsContent value="stacks">
        <OwalStacksTable data={stacks} />
      </TabsContent>
    </Tabs>
  );
};

export default OwalPageTabs;
