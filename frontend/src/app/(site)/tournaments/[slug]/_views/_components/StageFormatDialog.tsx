"use client";

import type { CSSProperties, JSX, ReactNode } from "react";
import { Info, Trophy } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";

import type { StageFormat } from "../tournamentOverview.model";
import { SectionLink } from "./OverviewCards";
import styles from "./StageFormatDialog.module.css";

/** Distinct team colours, handed out in this order by every diagram. Gold is the trophy's. */
const TEAM = ["teal", "rose", "amber", "violet", "blue", "emerald", "silver", "bronze"].map(
  (tone) => `var(--aqt-${tone})`
);

/** Bracket columns: the x of each round's slots, every slot 56 wide. */
const COL = [8, 92, 176, 260];
const SLOT_W = 56;

/** When a piece of a diagram starts animating, in ms after the dialog opens. */
const at = (ms: number) => ({ "--at": `${ms}ms` }) as CSSProperties;

/**
 * One team in a bracket. `out`: when its run in this part of the bracket ends
 * and it dims; `win`: when it takes the whole thing and lights up.
 */
function Slot({
  x,
  cy,
  team,
  show,
  out,
  win
}: Readonly<{ x: number; cy: number; team: number; show: number; out?: number; win?: number }>) {
  return (
    <g className={styles.pop} style={at(show)}>
      <g className={out === undefined ? undefined : styles.out} style={out === undefined ? undefined : at(out)}>
        <rect
          x={x}
          y={cy - 7}
          width={SLOT_W}
          height={14}
          rx={3}
          className={cn(styles.slot, win !== undefined && styles.champion)}
          style={win === undefined ? undefined : at(win)}
        />
        <circle cx={x + 8} cy={cy} r={3} style={{ fill: TEAM[team] }} />
        <rect x={x + 15} y={cy - 1.5} width={28} height={3} rx={1.5} className={styles.name} />
      </g>
    </g>
  );
}

/** A connector, drawn from its start. Keep each one a single subpath. */
function Wire({ d, show, tone }: Readonly<{ d: string; show: number; tone?: "win" | "loss" }>) {
  return <path d={d} pathLength={1} className={cn(styles.wire, tone && styles[tone])} style={at(show)} />;
}

/** A first loss sending a team down to the lower bracket. */
function Drop({ d, show }: Readonly<{ d: string; show: number }>) {
  return <path d={d} className={cn(styles.drop, styles.fade)} style={at(show)} />;
}

function Caption({ x, y, show = 0, children }: Readonly<{ x: number; y: number; show?: number; children: ReactNode }>) {
  return (
    <text x={x} y={y} className={cn(styles.caption, styles.fade)} style={at(show)}>
      {children}
    </text>
  );
}

function Champion({ x, cy, show }: Readonly<{ x: number; cy: number; show: number }>) {
  return (
    <g className={styles.pop} style={at(show)}>
      <Trophy x={x} y={cy - 7} size={14} className={styles.trophy} />
    </g>
  );
}

function Schema({ height, children }: Readonly<{ height: number; children: ReactNode }>) {
  return (
    <svg viewBox={`0 0 360 ${height}`} className={styles.schema} aria-hidden>
      {children}
    </svg>
  );
}

/** Five teams, each round two matches while the fifth sits out. */
const RR_TEAMS = 5;
const RR_ROUND_MS = 320;
/** The final table, top to bottom: team and points out of its four games. */
const RR_TABLE = [
  [2, 4],
  [0, 3],
  [4, 2],
  [1, 1],
  [3, 0]
];

function RoundRobinSchema() {
  const t = useTranslations("tournamentDetail.overview.format.schema");
  const node = (team: number) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * team) / RR_TEAMS;
    return [(88 + 64 * Math.cos(angle)).toFixed(1), (88 + 64 * Math.sin(angle)).toFixed(1)];
  };
  const tableAt = 350 + RR_TEAMS * RR_ROUND_MS;
  return (
    <Schema height={168}>
      {/* Circle method: round r pairs r+1 with r+4 and r+2 with r+3, r sits out. */}
      {Array.from({ length: RR_TEAMS }, (_, round) =>
        [
          [1, 4],
          [2, 3]
        ].map(([p, q]) => {
          const [a, b] = [(round + p) % RR_TEAMS, (round + q) % RR_TEAMS];
          const [[x1, y1], [x2, y2]] = [node(a), node(b)];
          return <Wire key={`${a}-${b}`} d={`M${x1} ${y1}L${x2} ${y2}`} show={350 + round * RR_ROUND_MS} />;
        })
      )}
      {Array.from({ length: RR_TEAMS }, (_, team) => {
        const [cx, cy] = node(team);
        return (
          <circle key={team} cx={cx} cy={cy} r={8} className={styles.pop} style={{ ...at(team * 50), fill: TEAM[team] }} />
        );
      })}
      <Caption x={200} y={22} show={tableAt}>
        {t("standings")}
      </Caption>
      {RR_TABLE.map(([team, points], row) => {
        const cy = 40 + 26 * row;
        const show = tableAt + row * 80;
        return (
          <g key={team}>
            <text x={200} y={cy + 4} className={cn(styles.record, styles.fade)} style={at(show)}>
              {row + 1}
            </text>
            <circle cx={218} cy={cy} r={4} className={styles.pop} style={{ ...at(show), fill: TEAM[team] }} />
            <rect
              x={230}
              y={cy - 5}
              width={12 + 28 * points}
              height={10}
              rx={2}
              className={styles.grow}
              style={{ ...at(show + 60), fill: TEAM[team], fillOpacity: 0.7 }}
            />
          </g>
        );
      })}
    </Schema>
  );
}

/** Columns of records after each round: column k holds k+1 rows, k–0 down to 0–k. */
const SWISS_ROUNDS = 4;
const SWISS_ROUND_MS = 650;

function SwissSchema() {
  const x = (round: number) => 8 + 96 * round;
  const cy = (round: number, losses: number) => 83 - 23 * round + 46 * losses;
  const columns = Array.from({ length: SWISS_ROUNDS }, (_, round) =>
    Array.from({ length: round + 1 }, (_, losses) => losses)
  );
  return (
    <Schema height={168}>
      {/* A win moves a team one row up, a loss one row down. */}
      {columns.slice(0, -1).flatMap((rows, round) =>
        rows.flatMap((losses) => {
          const [x1, y1, x2] = [x(round) + SLOT_W, cy(round, losses), x(round + 1)];
          const mid = (x1 + x2) / 2;
          const show = round * SWISS_ROUND_MS + 300;
          const curve = (y2: number) => `M${x1} ${y1}C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`;
          return [
            <Wire key={`${round}-${losses}-w`} d={curve(cy(round + 1, losses))} show={show} tone="win" />,
            <Wire key={`${round}-${losses}-l`} d={curve(cy(round + 1, losses + 1))} show={show} tone="loss" />
          ];
        })
      )}
      {columns.flatMap((rows, round) =>
        rows.map((losses) => (
          <g key={`${round}-${losses}`} className={styles.pop} style={at(round * SWISS_ROUND_MS + losses * 40)}>
            <rect x={x(round)} y={cy(round, losses) - 11} width={SLOT_W} height={22} rx={4} className={styles.slot} />
            <text
              x={x(round) + SLOT_W / 2}
              y={cy(round, losses) + 4}
              textAnchor="middle"
              className={styles.record}
            >
              {`${round - losses}–${losses}`}
            </text>
          </g>
        ))
      )}
    </Schema>
  );
}

/** Six teams over three lobby games: placement points per game, rows in the order of the totals. */
const FFA_GAMES = [
  [10, 7, 10],
  [7, 10, 5],
  [5, 3, 7],
  [3, 5, 3],
  [2, 1, 2],
  [1, 2, 1]
];
const FFA_GAME_MS = 650;
const FFA_UNIT = 7.5;
const FFA_GAME_OPACITY = [0.9, 0.65, 0.4];

function FfaSchema() {
  const t = useTranslations("tournamentDetail.overview.format.schema");
  return (
    <Schema height={168}>
      <Caption x={8} y={14}>
        {t("lobby")}
      </Caption>
      <rect x={8} y={22} width={96} height={136} rx={10} className={cn(styles.slot, styles.fade)} />
      {FFA_GAMES.map((_, team) => (
        <circle
          key={team}
          cx={40 + 32 * (team % 2)}
          cy={52 + 38 * Math.floor(team / 2)}
          r={8}
          className={styles.pop}
          style={{ ...at(150 + team * 50), fill: TEAM[team] }}
        />
      ))}
      <Caption x={128} y={14} show={450}>
        {t("standings")}
      </Caption>
      {FFA_GAMES.map((games, team) => {
        const cy = 30 + 22 * team;
        return (
          <g key={team}>
            <circle cx={128} cy={cy} r={4} className={styles.pop} style={{ ...at(450 + team * 40), fill: TEAM[team] }} />
            {games.map((points, game) => (
              <rect
                key={game}
                x={140 + games.slice(0, game).reduce((sum, prior) => sum + prior * FFA_UNIT + 1.5, 0)}
                y={cy - 5}
                width={points * FFA_UNIT}
                height={10}
                rx={2}
                className={styles.grow}
                style={{
                  ...at(600 + game * FFA_GAME_MS + team * 50),
                  fill: TEAM[team],
                  fillOpacity: FFA_GAME_OPACITY[game]
                }}
              />
            ))}
          </g>
        );
      })}
    </Schema>
  );
}

/** Eight teams round by round: each adjacent pair is a match, its winner the team listed next round. */
const KNOCKOUT = [[0, 1, 2, 3, 4, 5, 6, 7], [0, 3, 4, 6], [0, 4], [4]];
const KNOCKOUT_ROUND_MS = 750;

function SingleEliminationSchema() {
  const centers = [KNOCKOUT[0].map((_, i) => 13 + 20 * i)];
  for (const round of KNOCKOUT.slice(1)) {
    const prev = centers[centers.length - 1];
    centers.push(round.map((_, i) => (prev[2 * i] + prev[2 * i + 1]) / 2));
  }
  const last = KNOCKOUT.length - 1;
  const end = last * KNOCKOUT_ROUND_MS;
  return (
    <Schema height={168}>
      {centers.slice(0, -1).flatMap((ys, round) => {
        const x = COL[round] + SLOT_W;
        const start = round * KNOCKOUT_ROUND_MS;
        return Array.from({ length: ys.length / 2 }, (_, match) => {
          const [a, b] = [ys[2 * match], ys[2 * match + 1]];
          return (
            <g key={`${round}-${match}`}>
              <Wire d={`M${x} ${a}H${x + 12}V${b}H${x}`} show={start + 200} />
              <Wire d={`M${x + 12} ${(a + b) / 2}H${COL[round + 1]}`} show={start + 420} />
            </g>
          );
        });
      })}
      {KNOCKOUT.flatMap((teams, round) =>
        teams.map((team, i) => {
          const next = KNOCKOUT[round + 1];
          return (
            <Slot
              key={`${round}-${team}`}
              x={COL[round]}
              cy={centers[round][i]}
              team={team}
              show={round * KNOCKOUT_ROUND_MS + i * 30}
              out={next && !next.includes(team) ? (round + 1) * KNOCKOUT_ROUND_MS : undefined}
              win={round === last ? end : undefined}
            />
          );
        })
      )}
      <Champion x={COL[last] + SLOT_W + 8} cy={centers[last][0]} show={end + 150} />
    </Schema>
  );
}

/**
 * Four teams. Upper bracket: 0 beats 1, 2 beats 3, then 0 beats 2. Lower
 * bracket: 3 beats 1, then 2, down from the upper final, beats 3. Grand
 * final: 0 beats 2.
 */
function DoubleEliminationSchema() {
  const t = useTranslations("tournamentDetail.overview.format.schema");
  return (
    <Schema height={180}>
      <Caption x={8} y={12}>
        {t("upper")}
      </Caption>
      <Caption x={8} y={176} show={1050}>
        {t("lower")}
      </Caption>
      <Caption x={260} y={76} show={1800}>
        {t("grandFinal")}
      </Caption>

      <Wire d="M64 32H76V50H64" show={250} />
      <Wire d="M76 41H92" show={450} />
      <Wire d="M64 72H76V90H64" show={250} />
      <Wire d="M76 81H92" show={450} />
      <Drop d="M8 50H3V146H92" show={900} />
      <Drop d="M36 97V128H92" show={900} />
      <Wire d="M148 41H160V81H148" show={1300} />
      <Wire d="M160 61H248V90H260" show={1500} />
      <Wire d="M148 128H160V146H148" show={1300} />
      <Wire d="M160 137H168V154H176" show={1500} />
      <Drop d="M120 88V104H204V111" show={1800} />
      <Wire d="M232 118H244V154H232" show={2250} />
      <Wire d="M244 136H252V108H260" show={2450} />
      <Wire d="M316 90H328V108H316" show={3000} />
      <Wire d="M328 99H334" show={3200} />

      <Slot x={COL[0]} cy={32} team={0} show={0} />
      <Slot x={COL[0]} cy={50} team={1} show={40} out={750} />
      <Slot x={COL[0]} cy={72} team={2} show={80} />
      <Slot x={COL[0]} cy={90} team={3} show={120} out={750} />
      <Slot x={COL[1]} cy={41} team={0} show={750} />
      <Slot x={COL[1]} cy={81} team={2} show={750} out={1800} />
      <Slot x={COL[1]} cy={128} team={3} show={1050} />
      <Slot x={COL[1]} cy={146} team={1} show={1050} out={1800} />
      <Slot x={COL[2]} cy={118} team={2} show={1950} />
      <Slot x={COL[2]} cy={154} team={3} show={1800} out={2750} />
      <Slot x={COL[3]} cy={90} team={0} show={1800} win={3350} />
      <Slot x={COL[3]} cy={108} team={2} show={2750} out={3350} />
      <Champion x={336} cy={99} show={3350} />
    </Schema>
  );
}

const SCHEMA: Record<StageFormat, () => JSX.Element> = {
  round_robin: RoundRobinSchema,
  swiss: SwissSchema,
  ffa_league: FfaSchema,
  single_elimination: SingleEliminationSchema,
  double_elimination: DoubleEliminationSchema
};

/**
 * A stage's format as a chip beside its name, opening what the format means:
 * a diagram that plays it out once (Radix mounts the content on every open,
 * so it replays each time), a few sentences, and the docs article.
 * `showLabel` false: the organizer already named the stage after its format,
 * so the chip is the icon alone and names the format for assistive tech.
 */
export function StageFormatDialog({
  format,
  name,
  stageName,
  showLabel
}: Readonly<{ format: StageFormat; name: string; stageName: string; showLabel: boolean }>) {
  const t = useTranslations("tournamentDetail.overview.format");
  const FormatSchema = SCHEMA[format];
  return (
    <Dialog>
      <DialogTrigger
        aria-label={showLabel ? undefined : name}
        className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-2 py-0.5 text-caption font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] motion-reduce:transition-none"
      >
        {showLabel ? name : null}
        <Info aria-hidden className="size-3.5 shrink-0" />
      </DialogTrigger>
      <DialogContent className="border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
        <DialogHeader className="pr-6 text-left">
          <Eyebrow>{stageName}</Eyebrow>
          <DialogTitle className="text-[color:var(--aqt-fg)]">{name}</DialogTitle>
        </DialogHeader>
        <div className="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] p-3">
          <FormatSchema />
        </div>
        <DialogDescription className="text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
          {t(`types.${format}.description`)}
        </DialogDescription>
        <p>
          <SectionLink href="/docs/players/tournaments">{t("learnMore")}</SectionLink>
        </p>
      </DialogContent>
    </Dialog>
  );
}
