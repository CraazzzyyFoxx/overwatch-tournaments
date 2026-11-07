"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { LeaderboardTable } from "@/components/flow/LeaderboardTable";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { DraftNode } from "@/lib/flow/flowDraft";
import { buildLeaderboardTable } from "@/lib/flow/leaderboardTable";
import type { FlowRead } from "@/types/flow.types";

import { Field, NumberField, SelectField } from "./fields";

type Config = Record<string, unknown>;
type Props = Readonly<{
  node: DraftNode;
  /** The admin read: results and participants feed the previews and pickers. */
  read: FlowRead;
  readOnly: boolean;
  onChange: (patch: Pick<DraftNode, "config">) => void;
}>;

const FILTER_MODES = ["top", "range", "per_item_top", "swiss_status", "manual"] as const;
const FILTER_DEFAULTS: Record<(typeof FILTER_MODES)[number], Config> = {
  top: { n: 1 },
  range: { from: 1, to: 1 },
  per_item_top: { n: 1 },
  swiss_status: { swiss_status: "qualified" },
  manual: { manual: [] }
};
const AGGREGATE_MODES = ["sum_all", "sum_last_n", "sum_best_n", "average"] as const;
const SCORE_PRESETS = ["stage_points", "placement_table", "formula"] as const;
const FORMULA_VARIABLES = "place, participants, points, wins, draws, losses, map_diff, buchholz, ffa_score";

const MODE_KEYS = { sum_all: "sumAll", sum_last_n: "lastN", sum_best_n: "bestN", average: "average" } as const;
const needsN = (mode: string) => mode === "sum_last_n" || mode === "sum_best_n";

/** A member or team a result row refers to, with the name the read carries. */
function participantsOf(read: FlowRead) {
  return (read.participants ?? []).map((p) => ({ id: (p.workspace_member_id ?? p.team_id) as number, name: p.name }));
}

function Remove({ label, disabled, onClick }: Readonly<{ label: string; disabled?: boolean; onClick: () => void }>) {
  return (
    <Button type="button" variant="ghost-destructive" size="icon-sm" aria-label={label} disabled={disabled} onClick={onClick}>
      <X aria-hidden />
    </Button>
  );
}

function FilterInspector({ node, read, readOnly, onChange }: Props) {
  const t = useTranslations("adminTournament.flow.pure");
  const config = node.config;
  const mode = (config.mode ?? "top") as (typeof FILTER_MODES)[number];
  const set = (patch: Config) => onChange({ config: { ...config, ...patch } });

  const source = read.edges.find((e) => e.target_node_id === node.id && e.target_port === "ranking");
  const names = new Map(participantsOf(read).map((p) => [p.id, p.name]));
  const rows = source
    ? read.results
        .filter((r) => r.node_id === source.source_node_id && r.port === source.source_port)
        .sort((a, b) => a.rank - b.rank)
        .map((r) => (r.workspace_member_id ?? r.team_id) as number | null)
        .filter((id): id is number => id != null)
    : [];
  const picked = new Set((config.manual as number[] | undefined) ?? []);

  return (
    <div className="space-y-3">
      <SelectField
        label={t("mode")}
        value={mode}
        options={FILTER_MODES.map((m) => [m, t(`filterModes.${m}`)] as const)}
        disabled={readOnly}
        onChange={(next) => onChange({ config: { mode: next, ...FILTER_DEFAULTS[next as typeof mode] } })}
      />
      {mode === "top" || mode === "per_item_top" ? (
        <NumberField label={t("keep")} min={1} value={(config.n as number | null) ?? null} disabled={readOnly} onChange={(n) => set({ n })} />
      ) : null}
      {mode === "per_item_top" ? (
        <NumberField label={t("upper")} min={1} value={(config.upper as number | null) ?? null} disabled={readOnly} onChange={(upper) => set({ upper })} />
      ) : null}
      {mode === "range" ? (
        <div className="grid grid-cols-2 gap-3">
          <NumberField label={t("from")} min={1} value={(config.from as number | null) ?? null} disabled={readOnly} onChange={(from) => set({ from })} />
          <NumberField label={t("to")} min={1} value={(config.to as number | null) ?? null} disabled={readOnly} onChange={(to) => set({ to })} />
        </div>
      ) : null}
      {mode === "swiss_status" ? (
        <SelectField
          label={t("status")}
          value={String(config.swiss_status ?? "qualified")}
          options={[
            ["qualified", t("qualified")],
            ["eliminated", t("eliminated")]
          ]}
          disabled={readOnly}
          onChange={(swiss_status) => set({ swiss_status })}
        />
      ) : null}
      {mode === "manual" ? (
        <div className="space-y-1">
          {rows.map((id) => (
            <Label key={id} className="flex items-center gap-2 font-normal">
              <Checkbox
                checked={picked.has(id)}
                disabled={readOnly}
                onCheckedChange={(on) => set({ manual: on ? [...picked, id] : [...picked].filter((p) => p !== id) })}
              />
              {names.get(id) ?? `#${id}`}
            </Label>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MergeInspector({ node, read }: Props) {
  const t = useTranslations("adminTournament.flow.pure");
  const inputs = read.edges
    .filter((e) => e.target_node_id === node.id)
    .sort((a, b) => a.id - b.id)
    .map((e) => read.nodes.find((n) => n.id === e.source_node_id)?.name ?? `#${e.source_node_id}`);
  return (
    <div className="space-y-2 text-caption">
      <p className="text-muted-foreground">{t("mergeHint")}</p>
      <ol className="list-inside list-decimal">
        {inputs.map((name, index) => (
          <li key={index}>{name}</li>
        ))}
      </ol>
    </div>
  );
}

type Bucket = { name: string; size: number | null };

function SplitInspector({ node, readOnly, onChange }: Props) {
  const t = useTranslations("adminTournament.flow.pure");
  const buckets = (node.config.buckets as Bucket[] | undefined) ?? [];
  const write = (next: Bucket[], serpentine = Boolean(node.config.serpentine)) => onChange({ config: { ...node.config, buckets: next, serpentine } });
  const edit = (index: number, patch: Partial<Bucket>) => write(buckets.map((b, i) => (i === index ? { ...b, ...patch } : b)));

  return (
    <div className="space-y-3">
      <p className="text-label font-semibold uppercase tracking-label text-muted-foreground">{t("buckets")}</p>
      {buckets.map((bucket, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input aria-label={t("bucketName")} value={bucket.name} disabled={readOnly} onChange={(e) => edit(index, { name: e.target.value })} />
          <NumberInput
            aria-label={t("bucketSize")}
            integer
            min={1}
            className="w-24"
            placeholder={index === buckets.length - 1 ? t("rest") : undefined}
            value={bucket.size}
            disabled={readOnly}
            onValueChange={(size) => edit(index, { size })}
          />
          <Remove label={t("removeBucket")} disabled={readOnly || buckets.length === 1} onClick={() => write(buckets.filter((_, i) => i !== index))} />
        </div>
      ))}
      <Button
        type="button"
        variant="dashed"
        size="sm"
        disabled={readOnly}
        onClick={() =>
          // A bucket that was "the rest" must now have a size of its own.
          write([...buckets.map((b, i) => (i === buckets.length - 1 && b.size === null ? { ...b, size: 1 } : b)), { name: t("bucketDefault", { n: buckets.length + 1 }), size: null }])
        }
      >
        <Plus aria-hidden />
        {t("addBucket")}
      </Button>
      <Label className="flex items-center gap-2 font-normal">
        <Switch checked={Boolean(node.config.serpentine)} disabled={readOnly} onCheckedChange={(on) => write(buckets, on)} />
        {t("serpentine")}
      </Label>
    </div>
  );
}

function Preview({ node, read }: Pick<Props, "node" | "read">) {
  const t = useTranslations("adminTournament.flow.pure");
  const table = node.id === null ? null : buildLeaderboardTable(read, node.id);
  if (!table || table.rows.length === 0) return null;
  return (
    <section className="space-y-2" aria-label={t("preview")}>
      <h4 className="text-caption font-semibold">{table.rows.some((r) => r.tentative) ? t("previewTentative") : t("preview")}</h4>
      <LeaderboardTable table={table} describe={false} />
    </section>
  );
}

function AggregateInspector({ node, readOnly, onChange }: Props) {
  const t = useTranslations("adminTournament.flow.pure");
  const tUnit = useTranslations("common.flow.unit");
  const config = node.config;
  const score = (config.score ?? {}) as { preset?: string; table?: Record<string, number>; formula?: string | null };
  const mode = String(config.mode ?? "sum_all");
  const preset = score.preset ?? "stage_points";
  const table = Object.entries(score.table ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  const set = (patch: Config) => onChange({ config: { ...config, ...patch } });
  const setScore = (patch: Config) => set({ score: { ...score, ...patch } });
  const setTable = (rows: [string, number][]) => setScore({ table: Object.fromEntries(rows) });

  return (
    <div className="space-y-3">
      <SelectField
        label={t("unit")}
        value={String(config.unit ?? "players")}
        options={[
          ["players", tUnit("players")],
          ["teams", tUnit("teams")]
        ]}
        disabled={readOnly}
        onChange={(unit) => set({ unit })}
      />
      <SelectField
        label={t("score")}
        value={preset}
        options={SCORE_PRESETS.map((p) => [p, t(`scores.${p}`)] as const)}
        disabled={readOnly}
        onChange={(next) => setScore({ preset: next })}
      />
      {preset === "placement_table" ? (
        <div className="space-y-2">
          {table.map(([place, points]) => (
            <div key={place} className="flex items-center gap-2">
              <span className="w-16 text-caption text-muted-foreground">
                {t("place")} {place}
              </span>
              <NumberInput aria-label={`${t("points")} ${place}`} value={points} disabled={readOnly} onValueChange={(next) => setTable(table.map(([p, v]) => [p, p === place ? (next ?? 0) : v]))} />
              <Remove label={t("removePlace", { place })} disabled={readOnly} onClick={() => setTable(table.filter(([p]) => p !== place))} />
            </div>
          ))}
          <Button
            type="button"
            variant="dashed"
            size="sm"
            disabled={readOnly}
            onClick={() => setTable([...table, [String(Math.max(0, ...table.map(([p]) => Number(p))) + 1), 0]])}
          >
            <Plus aria-hidden />
            {t("addPlace")}
          </Button>
        </div>
      ) : null}
      {preset === "formula" ? (
        <Field label={t("formula")}>
          {(id) => (
            <>
              <Textarea id={id} value={score.formula ?? ""} disabled={readOnly} onChange={(e) => setScore({ formula: e.target.value })} />
              <p className="text-caption text-muted-foreground">{t("variables", { list: FORMULA_VARIABLES })}</p>
            </>
          )}
        </Field>
      ) : null}
      <SelectField
        label={t("mode")}
        value={mode}
        options={AGGREGATE_MODES.map((m) => [m, t(`aggregateModes.${MODE_KEYS[m]}`)] as const)}
        disabled={readOnly}
        onChange={(next) => set({ mode: next, n: needsN(next) ? ((config.n as number | null) ?? 1) : null })}
      />
      {needsN(mode) ? <NumberField label={t("count")} min={1} value={(config.n as number | null) ?? null} disabled={readOnly} onChange={(n) => set({ n })} /> : null}
    </div>
  );
}

type Pin = { participant_id: number; position: number };

function LeaderboardInspector({ node, read, readOnly, onChange }: Props) {
  const t = useTranslations("adminTournament.flow.pure");
  const pins = (node.config.pins as Pin[] | undefined) ?? [];
  const people = participantsOf(read);
  const write = (next: Pin[]) => onChange({ config: { ...node.config, pins: next } });
  const edit = (index: number, patch: Partial<Pin>) => write(pins.map((p, i) => (i === index ? { ...p, ...patch } : p)));

  return (
    <div className="space-y-3">
      <Preview node={node} read={read} />
      <p className="text-label font-semibold uppercase tracking-label text-muted-foreground">{t("pins")}</p>
      {pins.map((pin, index) => (
        <div key={index} className="flex items-end gap-2">
          <div className="flex-1">
            <SelectField
              label={t("participant")}
              value={String(pin.participant_id)}
              options={people.map((p) => [String(p.id), p.name] as const)}
              disabled={readOnly}
              onChange={(id) => edit(index, { participant_id: Number(id) })}
            />
          </div>
          <NumberField label={t("position")} min={1} value={pin.position} disabled={readOnly} onChange={(position) => edit(index, { position: position ?? 1 })} />
          <Remove label={t("removePin")} disabled={readOnly} onClick={() => write(pins.filter((_, i) => i !== index))} />
        </div>
      ))}
      <Button type="button" variant="dashed" size="sm" disabled={readOnly || people.length === 0} onClick={() => write([...pins, { participant_id: people[0].id, position: pins.length + 1 }])}>
        <Plus aria-hidden />
        {t("addPin")}
      </Button>
    </div>
  );
}

/** The config form of a transition node (filter, merge, split, aggregate, leaderboard); every edit writes the whole config. */
export function PureInspector(props: Props) {
  switch (props.node.kind) {
    case "filter":
      return <FilterInspector {...props} />;
    case "merge":
      return <MergeInspector {...props} />;
    case "split":
      return <SplitInspector {...props} />;
    case "aggregate":
      return <AggregateInspector {...props} />;
    case "leaderboard":
      return <LeaderboardInspector {...props} />;
    default:
      return null;
  }
}
