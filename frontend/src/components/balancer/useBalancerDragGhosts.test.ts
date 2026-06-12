import {
  applyDragEvent,
  pruneStaleDrags,
  type DragEventData,
  type RemoteDrag,
} from "@/components/balancer/useBalancerDragGhosts";

type TestFunction = () => void | Promise<void>;
type Expectation<T> = {
  toBe: (expected: T) => void;
  toEqual: (expected: unknown) => void;
  toBeUndefined: () => void;
};

declare const describe: (name: string, fn: TestFunction) => void;
declare const it: (name: string, fn: TestFunction) => void;
declare const expect: <T>(actual: T) => Expectation<T>;

const startData: DragEventData = {
  phase: "start",
  player_id: "7",
  player_name: "Echo",
  from_team_index: 0,
  from_role_key: "Damage",
};

const overData: DragEventData = {
  ...startData,
  phase: "over",
  over_team_index: 1,
  over_role_key: "Tank",
  over_insert_index: null,
};

describe("applyDragEvent", () => {
  it("ignores frames from the current user", () => {
    const result = applyDragEvent({}, 5, startData, 5, 1000);
    expect(result).toEqual({});
  });

  it("ignores frames with no actor", () => {
    const result = applyDragEvent({}, null, startData, 5, 1000);
    expect(result).toEqual({});
  });

  it("adds a ghost on start and updates it on over", () => {
    const afterStart = applyDragEvent({}, 9, startData, 5, 1000);
    expect(afterStart[9]?.playerName).toBe("Echo");
    expect(afterStart[9]?.overTeamIndex).toBe(null);

    const afterOver = applyDragEvent(afterStart, 9, overData, 5, 1100);
    expect(afterOver[9]?.overTeamIndex).toBe(1);
    expect(afterOver[9]?.overRoleKey).toBe("Tank");
    expect(afterOver[9]?.updatedAt).toBe(1100);
  });

  it("removes the ghost on end", () => {
    const afterStart = applyDragEvent({}, 9, startData, 5, 1000);
    const afterEnd = applyDragEvent(afterStart, 9, { phase: "end" }, 5, 1200);
    expect(afterEnd[9]).toBeUndefined();
  });

  it("returns the same map when ending an unknown drag", () => {
    const drags: Record<number, RemoteDrag> = {};
    const result = applyDragEvent(drags, 9, { phase: "end" }, 5, 1200);
    expect(result).toBe(drags);
  });
});

describe("pruneStaleDrags", () => {
  it("drops ghosts older than the TTL and keeps fresh ones", () => {
    const drags = {
      ...applyDragEvent({}, 1, startData, 99, 1000),
      ...applyDragEvent({}, 2, startData, 99, 5000),
    };
    const pruned = pruneStaleDrags(drags, 5500, 2000);
    expect(pruned[1]).toBeUndefined();
    expect(pruned[2]?.userId).toBe(2);
  });

  it("returns the same reference when nothing is stale", () => {
    const drags = applyDragEvent({}, 1, startData, 99, 5000);
    const pruned = pruneStaleDrags(drags, 5500, 2000);
    expect(pruned).toBe(drags);
  });
});
