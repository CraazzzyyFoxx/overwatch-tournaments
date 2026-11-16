import ProfileWidget from "@/components/profile/ProfileWidget";
import { PageStateCard } from "@/components/ui/page-state-card";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { User } from "@/types/user.types";

/** The ladder tab: the game's own career view (`careerTab`); a game with none says so. */
const UserLadderPage = ({
  user,
  scope,
  discipline,
  axis
}: {
  user: User;
  scope: StatsScope;
  discipline: string;
  axis: WorkspaceAxis;
}) => (
  <ProfileWidget
    key={discipline}
    axis={axis}
    discipline={discipline}
    slot="careerTab"
    props={{ userId: user.id, scope }}
    fallback={<PageStateCard state="empty" className="aqt-player" />}
  />
);

export default UserLadderPage;
