import { Suspense } from "react";

import HeroLeaderboardContent from "./components/HeroLeaderboardContent";

const HeroesComparePage = () => (
  <Suspense fallback={null}>
    <HeroLeaderboardContent />
  </Suspense>
);

export default HeroesComparePage;
