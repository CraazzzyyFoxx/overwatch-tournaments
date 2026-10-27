import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";
import { getTranslations } from "next-intl/server";

import FlexIcon from "@/components/icons/FlexIcon";
import disciplineService from "@/services/discipline.service";
import { findRole, rolePresentation, type RoleOntology } from "@/lib/roster/ontology";
import { SITE_NAME, SITE_URL_OBJ } from "@/config/site";
import { getFormatter } from "@/lib/datetime/server";
import { bracketRoundLabel, UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import {
  getDivisionIconSrc,
  type DivisionGridLike
} from "@/lib/divisions/grid";
import { duelSeats, isLobby } from "@/lib/encounter/seats";
import { getEncounterState, isEncounterCompleted } from "@/lib/encounter/status";
import { sortTeamPlayers, splitHandle } from "@/lib/player";
import encounterService from "@/services/encounter.service";
import type { Encounter } from "@/types/encounter.types";
import type { Player, Team } from "@/types/team.types";

import { ACCENT, BG, FAINT, FG, LINE, MUTED, OG_SIZE, loadOgFonts } from "./base";

/**
 * Rank crests, inlined. `getDivisionIconSrc` hands back a site-relative path
 * for every stock grid, and those files sit in `public/` right next to the
 * running server — reading them beats sixteen HTTP round-trips back into our
 * own origin per card, which is also one more thing that can be down while
 * Discord waits. A workspace grid may instead store an absolute S3 crest;
 * that one stays a URL for Satori to fetch.
 */
const crestCache = new Map<string, string | null>();

/** A tournament without a resolved grid has no crests: the card renders without them, never another game's. */
const NO_GRID: DivisionGridLike = { tiers: [] };

async function resolveCrests(grid: DivisionGridLike, teams: (Team | null)[]) {
  const sources = new Set<string>();
  for (const team of teams) {
    for (const player of team?.players ?? []) {
      const src = getDivisionIconSrc(grid, player.division);
      if (src) sources.add(src);
    }
  }

  const resolved = new Map<string, string>();
  await Promise.all(
    [...sources].map(async (src) => {
      if (!crestCache.has(src)) {
        crestCache.set(
          src,
          src.startsWith("http")
            ? src
            : await readFile(join(process.cwd(), "public", src))
                .then((data) => `data:image/png;base64,${data.toString("base64")}`)
                .catch((error) => {
                  console.error(`opengraph-image: missing crest ${src}:`, error);
                  return null;
                })
        );
      }
      const crest = crestCache.get(src);
      if (crest) resolved.set(src, crest);
    })
  );
  return resolved;
}

/** Satori has no CSS masks. Tint the white module SVG bytes at this server-only boundary. */
async function resolveRoleArtwork(ontology: RoleOntology | null): Promise<Map<number, string>> {
  const icons = new Map<number, string>();
  if (!ontology) return icons;
  for (const role of ontology.roles) {
    const presentation = rolePresentation(ontology.roles, role.id);
    const icon = presentation.icon;
    if (!icon) continue;
    if (icon.startsWith(`/disciplines/${ontology.discipline.code}/`) && icon.endsWith(".svg") && !icon.includes("..")) {
      try {
        let svg = await readFile(join(process.cwd(), "public", icon), "utf8");
        if (presentation.color && /^#[0-9a-fA-F]{6}$/.test(presentation.color)) svg = svg.replaceAll("#ffffff", presentation.color);
        icons.set(role.id, `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`);
      } catch (error) {
        console.error(`opengraph-image: missing role icon ${icon}:`, error);
      }
    } else {
      icons.set(role.id, new URL(icon, SITE_URL_OBJ).toString());
    }
  }
  return icons;
}

/** `EncounterState` sentinels are English words; the catalog keys are camelCase. */
const STATE_KEY: Record<string, string> = {
  Live: "live",
  Upcoming: "upcoming",
  Final: "final",
  Pending: "pending",
  Open: "open"
};

function RosterRow({
  player,
  divisionIcon,
  isCaptain,
  subLabel,
  ontology,
  roleArtwork
}: {
  player: Player;
  divisionIcon: string | null;
  isCaptain: boolean;
  subLabel: string;
  ontology: RoleOntology | null;
  roleArtwork: Map<number, string>;
}) {
  const role = ontology ? findRole(ontology, player.role) : null;
  const icon = role ? roleArtwork.get(role.id) : null;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        height: 44,
        opacity: player.is_substitution ? 0.72 : 1
      }}
    >
      {/* The slot is kept even for an unknown role, so nicks line up. */}
      <div style={{ display: "flex", width: 22, height: 22, alignItems: "center" }}>
        {!player.role ? <FlexIcon width={22} height={22} color={MUTED} /> : icon ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={icon} alt={role?.name ?? player.role.role} width={22} height={22} />
        ) : <span style={{ color: MUTED, fontSize: 14 }}>{role?.name.slice(0, 2).toUpperCase() ?? "?"}</span>}
      </div>
      {divisionIcon ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={divisionIcon} alt="" width={26} height={26} />
      ) : (
        <div style={{ display: "flex", width: 26, height: 26 }} />
      )}
      <div
        style={{
          display: "flex",
          fontSize: 24,
          fontWeight: isCaptain ? 700 : 400,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: 240
        }}
      >
        {/* The BattleTag discriminator is noise at this size. */}
        {splitHandle(player.name).name}
      </div>
      {isCaptain ? (
        <div style={{ display: "flex", fontSize: 20, color: ACCENT, fontWeight: 700 }}>C</div>
      ) : null}
      {player.is_substitution ? (
        <div
          style={{
            display: "flex",
            fontSize: 16,
            color: FAINT,
            border: `1px solid ${LINE}`,
            borderRadius: 6,
            padding: "1px 6px"
          }}
        >
          {subLabel}
        </div>
      ) : null}
      <div style={{ display: "flex", flexGrow: 1 }} />
      <div style={{ display: "flex", fontSize: 20, color: FAINT }}>{player.rank ?? "—"}</div>
    </div>
  );
}

function TeamColumn({
  team,
  grid,
  crests,
  align,
  tbd,
  srLabel,
  subLabel,
  ontology,
  roleArtwork
}: {
  team: Team | null;
  grid: DivisionGridLike;
  crests: Map<string, string>;
  align: "flex-start" | "flex-end";
  tbd: string;
  srLabel: string;
  subLabel: string;
  ontology: RoleOntology | null;
  roleArtwork: Map<number, string>;
}) {
  if (!team) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          flexGrow: 1,
          flexBasis: 0,
          alignItems: align,
          justifyContent: "center"
        }}
      >
        <div style={{ display: "flex", fontSize: 44, fontWeight: 700, color: FAINT }}>{tbd}</div>
      </div>
    );
  }

  // Eight rows is the tallest roster the band fits; a deeper bench is cut
  // rather than pushed off the bottom edge.
  const players = sortTeamPlayers(team.players ?? [], ontology).slice(0, 8);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flexGrow: 1,
        flexBasis: 0,
        alignItems: align,
        gap: 14
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {team.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={new URL(team.image_url, SITE_URL_OBJ).toString()}
            alt=""
            width={56}
            height={56}
            style={{ borderRadius: 12, objectFit: "cover" }}
          />
        ) : null}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              fontSize: 36,
              fontWeight: 700,
              maxWidth: 380,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap"
            }}
          >
            {team.name}
          </div>
          <div style={{ display: "flex", fontSize: 20, color: MUTED }}>
            {srLabel} {Math.round(team.avg_sr)}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
        {players.map((player) => {
          const src = getDivisionIconSrc(grid, player.division);
          return (
            <RosterRow
              key={player.id}
              player={player}
              divisionIcon={(src && crests.get(src)) ?? null}
              isCaptain={player.user_id === team.captain_id}
              subLabel={subLabel}
              ontology={ontology}
              roleArtwork={roleArtwork}
            />
          );
        })}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: BG,
        color: FG,
        padding: "40px 56px",
        fontFamily: "Onest"
      }}
    >
      {children}
    </div>
  );
}

/**
 * Open Graph card for one encounter — the unfurl of `/encounters/{id}` and of
 * the pre-game room, and the image Discord embeds inside the "your match is
 * ready" card itself.
 *
 * A duel renders both rosters side by side; an FFA lobby has no two sides to
 * compare, so it gets a plain card the way the detail page does. Any failure to
 * load the encounter (a tournament hidden from anonymous crawlers 404s here)
 * falls back to a branded card rather than a broken image.
 */
export async function renderEncounterOg(encounterId: number) {
  const options = { ...OG_SIZE, fonts: await loadOgFonts() };

  let encounter: Encounter;
  try {
    encounter = await encounterService.getEncounter(encounterId);
  } catch (error) {
    console.error(`opengraph-image: failed to load encounter ${encounterId}:`, error);
    return new ImageResponse(
      <Shell>
        <div style={{ display: "flex", flexGrow: 1, alignItems: "center" }}>
          <div style={{ display: "flex", fontSize: 72, fontWeight: 700 }}>{SITE_NAME}</div>
        </div>
      </Shell>,
      options
    );
  }

  const t = await getTranslations();
  const format = await getFormatter();

  // The bracket's own round name ("LB Round 1", not "Round -1"). No round list
  // here, so no round is promoted to a final on a guess.
  const round = bracketRoundLabel(encounter.round, UNKNOWN_ROUND_SHAPE);
  const header = (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div
          style={{
            display: "flex",
            fontSize: 34,
            fontWeight: 700,
            maxWidth: 820,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap"
          }}
        >
          {encounter.tournament?.name ?? t("common.tournament")}
        </div>
        <div style={{ display: "flex", fontSize: 24, fontWeight: 700, color: MUTED }}>
          {SITE_NAME}
        </div>
      </div>
      <div style={{ display: "flex", fontSize: 22, color: FAINT }}>
        {[
          encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage"),
          round.n === undefined
            ? t(`bracket.${round.key}`)
            : t(`bracket.${round.key}`, { n: String(round.n) }),
          t("encounters.bestOfShort", { count: encounter.best_of })
        ].join("  ·  ")}
      </div>
    </div>
  );

  if (isLobby(encounter)) {
    return new ImageResponse(
      <Shell>
        {header}
        <div
          style={{
            display: "flex",
            flexGrow: 1,
            flexDirection: "column",
            justifyContent: "center",
            gap: 12
          }}
        >
          <div style={{ display: "flex", fontSize: 72, fontWeight: 700 }}>{encounter.name}</div>
          <div style={{ display: "flex", fontSize: 28, color: MUTED }}>
            {t(`encounters.state.${STATE_KEY[getEncounterState(encounter)]}` as never)}
          </div>
        </div>
      </Shell>,
      options
    );
  }

  const [one, two] = duelSeats(encounter.teams);
  const completed = isEncounterCompleted(encounter);
  const scheduledAt = encounter.scheduled_at ? new Date(encounter.scheduled_at) : null;
  const center = completed
    ? `${one?.score ?? 0} : ${two?.score ?? 0}`
    : scheduledAt
      ? format.dateTime(scheduledAt, { dateStyle: "medium", timeStyle: "short" })
      : t("common.tbd");

  const grid = encounter.tournament?.division_grid_version ?? NO_GRID;
  const crests = await resolveCrests(grid, [one?.team ?? null, two?.team ?? null]);
  const ontology = await disciplineService.metadata(encounter.workspace_id, encounter.discipline).catch(error => {
    console.error("opengraph-image: role metadata unavailable:", error);
    return null;
  });
  const roleArtwork = await resolveRoleArtwork(ontology);

  return new ImageResponse(
    <Shell>
      {header}
      {/* The band is centred in the card (a five-man roster would otherwise
            leave a third of it empty), but the columns stretch to one height so
            both rosters start on the same line; VS and a TBD side centre in it. */}
      <div
        style={{
          display: "flex",
          flexGrow: 1,
          flexDirection: "column",
          justifyContent: "center",
          paddingTop: 12
        }}
      >
        <div style={{ display: "flex", alignItems: "stretch" }}>
          <TeamColumn
            team={one?.team ?? null}
            grid={grid}
            crests={crests}
            ontology={ontology}
            roleArtwork={roleArtwork}
            align="flex-start"
            tbd={t("common.tbd")}
            srLabel={t("teams.roster.avgSr")}
            subLabel={t("teams.roster.substitution")}
          />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
              width: 220
            }}
          >
            <div style={{ display: "flex", fontSize: 26, color: FAINT, fontWeight: 700 }}>VS</div>
            <div
              style={{
                display: "flex",
                fontSize: completed ? 60 : 24,
                fontWeight: 700,
                color: completed ? FG : ACCENT,
                textAlign: "center"
              }}
            >
              {center}
            </div>
          </div>
          <TeamColumn
            team={two?.team ?? null}
            grid={grid}
            crests={crests}
            ontology={ontology}
            roleArtwork={roleArtwork}
            align="flex-end"
            tbd={t("common.tbd")}
            srLabel={t("teams.roster.avgSr")}
            subLabel={t("teams.roster.substitution")}
          />
        </div>
      </div>
    </Shell>,
    options
  );
}
