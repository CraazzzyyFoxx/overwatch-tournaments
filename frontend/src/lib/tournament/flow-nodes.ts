import type { DraftFormatSettings } from "@/types/draft.types";
import type { Tournament } from "@/types/tournament.types";
import type { TournamentFlowNode } from "@/types/flow.types";

export type FormationMode = "balancer" | "draft" | "registered" | "manual";

/** The draft rule a formation node drafts with (`config.draft_format`, only read in `draft` mode); `null` = the snake default. */
export function nodeDraftFormat(node: Pick<TournamentFlowNode, "config"> | null | undefined): DraftFormatSettings | null {
  return (node?.config.draft_format as DraftFormatSettings | null | undefined) ?? null;
}

/** The modes of the tournament's formation nodes. Empty when the read did not ask for `flow_nodes`, or the graph has no formation. */
export function formationModes(tournament: Pick<Tournament, "flow_nodes"> | null | undefined): Set<FormationMode> {
  return new Set(nodesOfKind(tournament, "formation").map((node) => node.config.mode as FormationMode));
}

/** Some registration node takes whole teams: registered teams exist and the organizer screens for them are offered. */
export function hasTeamIntake(tournament: Pick<Tournament, "flow_nodes"> | null | undefined): boolean {
  return nodesOfKind(tournament, "registration").some((node) => registrationIntake(tournament, node) === "team");
}

/** The mode of the first formation by graph order (node id), or null when there is none: what a card or a chip says the tournament is. */
export function primaryFormationMode(tournament: Pick<Tournament, "flow_nodes"> | null | undefined): FormationMode | null {
  return (nodesOfKind(tournament, "formation")[0]?.config.mode as FormationMode | undefined) ?? null;
}

/** `team` when the registration node (default: the current one) takes whole teams, else `solo`. */
export function registrationIntake(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  node: Pick<TournamentFlowNode, "config"> | null = currentRegistrationNode(tournament)
): "solo" | "team" {
  return registrationNodeConfig(node).intake;
}

/** The tournament's nodes of one lifecycle kind, in id order; empty when the read did not ask for `flow_nodes`. */
export function nodesOfKind(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  kind: `${TournamentFlowNode["kind"]}`
): TournamentFlowNode[] {
  return (tournament?.flow_nodes ?? []).filter((node) => `${node.kind}` === kind).sort((a, b) => a.id - b.id);
}

/** The formation node that forms teams by draft: the one a tournament's public draft room follows. */
export function draftFormationNode(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined
): TournamentFlowNode | null {
  return nodesOfKind(tournament, "formation").find((node) => node.config.mode === "draft") ?? null;
}

/**
 * Every registration node feeding a formation, newest first (`pool_registration_node_ids`): a formation screen lists the
 * union of their entries, the newest node's entry deciding per member (Decision 9). Empty for no formation, or a
 * formation no registration feeds.
 */
export function poolRegistrationNodeIds(
  formation: Pick<TournamentFlowNode, "pool_registration_node_ids"> | null | undefined
): number[] {
  return formation?.pool_registration_node_ids ?? [];
}

/**
 * The registration node the public site's single register button is bound to: the node in `check_in` where the viewer
 * already has an entry (`entryNodeIds`, so a Day 1 entrant can still check in while Day 2 is `open`), else the first one
 * `open`, else the first in `check_in`, else the latest non-`draft` one, else none. A viewer with no entry is offered the
 * `open` intake first: a check-in has nothing for them to confirm.
 */
export function currentRegistrationNode(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  entryNodeIds: readonly number[] = []
): TournamentFlowNode | null {
  const nodes = nodesOfKind(tournament, "registration");
  return (
    nodes.find((node) => node.status === "check_in" && entryNodeIds.includes(node.id)) ??
    nodes.find((node) => node.status === "open") ??
    nodes.find((node) => node.status === "check_in") ??
    [...nodes].reverse().find((node) => node.status !== "draft") ??
    null
  );
}

/**
 * The registration node whose roster the public lists show: `node` (default: the current one), else the first
 * registration node. Before any intake opens every node is `draft` and there is no current one, but the roster still
 * exists (empty, or what an organizer added) and the page must not wait for a node that will never come.
 */
export function listedRegistrationNode(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  node: TournamentFlowNode | null = currentRegistrationNode(tournament)
): TournamentFlowNode | null {
  return node ?? nodesOfKind(tournament, "registration")[0] ?? null;
}

/** The registration node's intake settings, as `RegistrationNodeConfig` (backend) stores them; absent keys read as its defaults. */
export interface RegistrationNodeConfig {
  check_in: boolean;
  intake: "solo" | "team";
  auto_approve: boolean;
  /** Advisory capacity, never a limit. */
  max_participants: number | null;
  max_substitutes: number;
  require_subscription: boolean;
  subscription_stage: "registration" | "check_in";
  subscription_scope: "player" | "team";
  team_rank_min: number | null;
  team_rank_max: number | null;
  team_max_rank_spread: number | null;
  team_unique_identity: boolean;
  team_require_discord_guild: boolean;
  allow_late_registration: boolean;
}

/** A registration node's config with the backend defaults filled in; the defaults for no node at all. */
export function registrationNodeConfig(node: Pick<TournamentFlowNode, "config"> | null | undefined): RegistrationNodeConfig {
  return {
    check_in: false,
    intake: "solo",
    auto_approve: false,
    max_participants: null,
    max_substitutes: 0,
    require_subscription: false,
    subscription_stage: "check_in",
    subscription_scope: "player",
    team_rank_min: null,
    team_rank_max: null,
    team_max_rank_spread: null,
    team_unique_identity: false,
    team_require_discord_guild: false,
    allow_late_registration: false,
    ...(node?.config as Partial<RegistrationNodeConfig> | undefined)
  };
}

/** When the current registration node's `open` window closes (ISO-8601), or null when it has none. */
export function registrationClosesAt(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined
): string | null {
  const node = currentRegistrationNode(tournament);
  return (node && scheduleRow(node, "open")?.ends_at) || null;
}

/** The earliest planned stage start (ISO-8601) across the stage nodes, or null when none is scheduled. */
export function playStartsAt(tournament: Pick<Tournament, "flow_nodes"> | null | undefined): string | null {
  const starts = nodesOfKind(tournament, "stage").flatMap((node) =>
    node.schedule.filter((entry) => entry.phase === "start").map((entry) => entry.starts_at)
  );
  return starts.sort((left, right) => Date.parse(left) - Date.parse(right))[0] ?? null;
}

function scheduleRow(node: Pick<TournamentFlowNode, "schedule">, phase: "open" | "check_in") {
  return node.schedule.find((entry) => entry.phase === phase);
}

/**
 * Mirrors `shared.services.registration_window.is_sign_up_open`: the node is `open` and inside its `open` row (no row:
 * the status decides), or in `check_in` with `allow_late_registration`, which lifts the row's `ends_at` and nothing else.
 * The client only decides whether to render the register button, so it must agree with the server.
 */
export function isSignUpOpen(node: TournamentFlowNode | null | undefined, now: number = Date.now()): boolean {
  if (!node) return false;
  const allowLate = registrationNodeConfig(node).allow_late_registration;
  if (node.status === "check_in") return allowLate;
  if (node.status !== "open") return false;
  const row = scheduleRow(node, "open");
  if (!row) return true;
  if (new Date(row.starts_at).getTime() > now) return false;
  return row.ends_at == null || allowLate || now <= new Date(row.ends_at).getTime();
}

/** Mirrors `is_sign_up_late`: a sign-up now is only possible past the announced closing time (it is written as a reserve). */
export function isSignUpLate(node: TournamentFlowNode | null | undefined, now: number = Date.now()): boolean {
  if (!node) return false;
  if (node.status === "check_in") return true;
  const row = scheduleRow(node, "open");
  if (node.status !== "open" || !row?.ends_at) return false;
  return new Date(row.starts_at).getTime() <= now && now > new Date(row.ends_at).getTime();
}

/** Mirrors `is_check_in_open`: the node is in `check_in` and inside its `check_in` row (no row: the status decides). */
export function isCheckInOpen(node: TournamentFlowNode | null | undefined, now: number = Date.now()): boolean {
  if (node?.status !== "check_in") return false;
  const row = scheduleRow(node, "check_in");
  if (!row) return true;
  return new Date(row.starts_at).getTime() <= now && (row.ends_at == null || now <= new Date(row.ends_at).getTime());
}
