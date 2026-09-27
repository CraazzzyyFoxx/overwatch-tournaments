"use client";

import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { OPERATORS, STATS } from "./condition-flow.model";

/** Stat select + operator/value row shared by `stat_threshold`/`global_stat_sum`
 * and `hero_stat` (which prefixes it with its own hero-slug input). */
function StatOpValueFields({
  params,
  setParam,
  controlName
}: Readonly<{
  params: Record<string, unknown>;
  setParam: (key: string, value: unknown) => void;
  controlName: (field: string) => string;
}>) {
  return (
    <>
      <Select value={(params.stat as string) ?? ""} onValueChange={(v) => setParam("stat", v)}>
        <SelectTrigger className="h-7 text-xs" aria-label={controlName("Stat")}><SelectValue placeholder="Stat…" /></SelectTrigger>
        <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
      </Select>
      <div className="flex gap-1">
        <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
          <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
          <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
        </Select>
        <NumberInput className="h-7 text-xs" aria-label={controlName("Threshold value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
      </div>
    </>
  );
}

/**
 * The inline parameter editors for one leaf condition. Which fields appear is
 * decided entirely by `conditionType`; every control is named through
 * `controlName` because thirty-odd param controls across the canvas share the
 * same handful of field names ("Operator", "Value").
 */
export function ConditionLeafFields({
  nodeId,
  conditionType,
  params,
  setParam,
  controlName
}: Readonly<{
  nodeId: string;
  conditionType: string | undefined;
  params: Record<string, unknown>;
  setParam: (key: string, value: unknown) => void;
  controlName: (field: string) => string;
}>) {
  const lostInRoundParam = params.lost_in_round;
  const lostInRound =
    lostInRoundParam !== null && typeof lostInRoundParam === "object"
      ? lostInRoundParam
      : null;
  const lostInRoundOp =
    lostInRound && "op" in lostInRound && typeof lostInRound.op === "string"
      ? lostInRound.op
      : undefined;
  const lostInRoundValue =
    lostInRound && "value" in lostInRound && typeof lostInRound.value === "number"
      ? lostInRound.value
      : 1;

  return (
    <div className="space-y-1.5 text-xs">
      {(conditionType === "stat_threshold" || conditionType === "global_stat_sum") && (
        <StatOpValueFields params={params} setParam={setParam} controlName={controlName} />
      )}
      {conditionType === "match_criteria" && (
        <>
          <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field…" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="closeness">Closeness</SelectItem>
              <SelectItem value="match_time">Match time</SelectItem>
            </SelectContent>
          </Select>
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput className="h-7 text-xs" aria-label={controlName("Threshold value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
          </div>
        </>
      )}
      {conditionType === "player_role" && (
        <Select value={(params.role as string) ?? "Damage"} onValueChange={(v) => setParam("role", v)}>
          <SelectTrigger className="h-7 text-xs" aria-label={controlName("Role")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="Tank">Tank</SelectItem>
            <SelectItem value="Damage">Damage</SelectItem>
            <SelectItem value="Support">Support</SelectItem>
          </SelectContent>
        </Select>
      )}
      {conditionType === "player_div" && (
        <div className="flex gap-1">
          <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
            <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
            <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
          </Select>
          <NumberInput integer className="h-7 text-xs" aria-label={controlName("Division")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
        </div>
      )}
      {/* ── op + value conditions ── */}
      {(conditionType === "standing_position" || conditionType === "tournament_count" || conditionType === "div_level") && (
        <div className="flex gap-1">
          <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
            <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
            <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
          </Select>
          <NumberInput integer className="h-7 text-xs" aria-label={controlName("Value")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
        </div>
      )}
      {/* ── standing_record: field + op + value ── */}
      {conditionType === "standing_record" && (
        <>
          <Select value={(params.field as string) ?? "wins"} onValueChange={(v) => setParam("field", v)}>
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field…" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="wins">Wins</SelectItem>
              <SelectItem value="losses">Losses</SelectItem>
              <SelectItem value="draws">Draws</SelectItem>
              <SelectItem value="points">Points</SelectItem>
              <SelectItem value="buchholz">Buchholz</SelectItem>
              <SelectItem value="matches">Matches</SelectItem>
            </SelectContent>
          </Select>
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput className="h-7 text-xs" aria-label={controlName("Value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
          </div>
        </>
      )}
      {/* ── div_change ── */}
      {conditionType === "div_change" && (
        <div className="flex gap-1">
          <Select value={(params.direction as string) ?? "up"} onValueChange={(v) => setParam("direction", v)}>
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Direction")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="up">Up</SelectItem>
              <SelectItem value="down">Down</SelectItem>
            </SelectContent>
          </Select>
          <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum shift")} placeholder="Min shift" value={(params.min_shift as number) ?? 1} onValueChange={(next) => setParam("min_shift", next ?? 1)} />
        </div>
      )}
      {/* ── hero_stat: hero + stat + op + value ── */}
      {conditionType === "hero_stat" && (
        <>
          <Input className="h-7 text-xs" aria-label={controlName("Hero slug")} placeholder="Hero slug (e.g. dva)" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
          <StatOpValueFields params={params} setParam={setParam} controlName={controlName} />
        </>
      )}
      {/* ── hero_kd_best ── */}
      {conditionType === "hero_kd_best" && (
        <>
          <Input className="h-7 text-xs" aria-label={controlName("Hero slug")} placeholder="Hero slug" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
          <div className="flex gap-1">
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum time played in seconds")} placeholder="Min time (s)" value={(params.min_time as number) ?? 600} onValueChange={(next) => setParam("min_time", next ?? 600)} />
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum matches")} placeholder="Min matches" value={(params.min_matches as number) ?? 3} onValueChange={(next) => setParam("min_matches", next ?? 3)} />
          </div>
        </>
      )}
      {/* ── global_winrate: order + limit + op/value ── */}
      {conditionType === "global_winrate" && (
        <>
          <div className="flex gap-1">
            <Select value={(params.order as string) ?? "desc"} onValueChange={(v) => setParam("order", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Ranking end")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="desc">Top</SelectItem>
                <SelectItem value="asc">Bottom</SelectItem>
              </SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Ranking limit")} placeholder="Limit" value={(params.limit as number) ?? 20} onValueChange={(next) => setParam("limit", next ?? 20)} />
          </div>
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? "none"} onValueChange={(v) => setParam("op", v === "none" ? undefined : v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Winrate operator")}><SelectValue placeholder="Op" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
              </SelectContent>
            </Select>
            {Boolean(params.op) && <NumberInput className="h-7 text-xs w-16" aria-label={controlName("Winrate")} placeholder="Rate" value={(params.value as number) ?? 0.5} onValueChange={(next) => setParam("value", next ?? 0.5)} />}
          </div>
        </>
      )}
      {/* ── consecutive: metric + streak + day_two position ── */}
      {conditionType === "consecutive" && (
        <>
          <div className="flex gap-1">
            <Select value={(params.metric as string) ?? "win"} onValueChange={(v) => setParam("metric", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Streak metric")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="win">Win</SelectItem>
                <SelectItem value="day_two">Day two</SelectItem>
              </SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum streak")} placeholder="Streak" value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
          </div>
          {(params.metric as string) === "day_two" && (
            <div className="flex gap-1 items-center">
              <p className="text-muted-foreground text-xs shrink-0">Position</p>
              <Select value={(params.position_op as string) ?? "<"} onValueChange={(v) => setParam("position_op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Position operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Position")} value={(params.position_value as number) ?? 7} onValueChange={(next) => setParam("position_value", next ?? 7)} />
            </div>
          )}
        </>
      )}
      {/* ── is_newcomer: bool or count mode ── */}
      {conditionType === "is_newcomer" && (
        <div className="flex gap-1">
          <Select
            value={params.op !== undefined ? "count" : "bool"}
            onValueChange={(v) => {
              if (v === "bool") {
                setParam("op", undefined);
                setParam("value", undefined);
              } else {
                setParam("op", params.op ?? ">=");
                setParam("value", params.value ?? 1);
              }
            }}
          >
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Newcomer mode")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="bool">Is newcomer</SelectItem>
              <SelectItem value="count">Count tournaments</SelectItem>
            </SelectContent>
          </Select>
          {params.op !== undefined && (
            <>
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Tournament count operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Tournament count")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
            </>
          )}
        </div>
      )}
      {/* ── tournament_type: any/league/not league ── */}
      {conditionType === "tournament_type" && (
        <Select
          value={params.is_league === null || params.is_league === undefined ? "any" : String(params.is_league)}
          onValueChange={(v) => setParam("is_league", v === "any" ? null : v === "true")}
        >
          <SelectTrigger className="h-7 text-xs" aria-label={controlName("Tournament type")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Any</SelectItem>
            <SelectItem value="true">League</SelectItem>
            <SelectItem value="false">Not league</SelectItem>
          </SelectContent>
        </Select>
      )}
      {/* ── encounter_score: round_type + scores + winner ── */}
      {conditionType === "encounter_score" && (
        <>
          <div className="flex gap-1">
            <Select value={(params.round_type as string) ?? "any"} onValueChange={(v) => setParam("round_type", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Round type")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any round</SelectItem>
                <SelectItem value="final">Final</SelectItem>
              </SelectContent>
            </Select>
            <Select value={String(params.winner ?? true)} onValueChange={(v) => setParam("winner", v === "true")}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Which side counts")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="true">Winner only</SelectItem>
                <SelectItem value="false">Both teams</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-xs">Score patterns (home–away)</p>
            {((params.scores as number[][]) ?? [[2, 3]]).map((pair, i) => (
              <div key={i} className="flex gap-1 items-center">
                <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName(`Home score of pattern ${i + 1}`)} value={pair[0]} onValueChange={(next) => {
                  const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                  scores[i] = [next ?? 0, scores[i][1]];
                  setParam("scores", scores);
                }} />
                <span className="text-xs text-muted-foreground" aria-hidden>–</span>
                <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName(`Away score of pattern ${i + 1}`)} value={pair[1]} onValueChange={(next) => {
                  const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                  scores[i] = [scores[i][0], next ?? 0];
                  setParam("scores", scores);
                }} />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  aria-label={controlName(`Remove score pattern ${i + 1}`)}
                  onClick={() => {
                    const scores = ((params.scores as number[][]) ?? [[2, 3]]).filter((_, idx) => idx !== i);
                    setParam("scores", scores.length > 0 ? scores : [[0, 0]]);
                  }}
                >
                  <X className="h-3 w-3 text-destructive" aria-hidden />
                </Button>
              </div>
            ))}
            <button
              type="button"
              className="flex items-center gap-1 text-xs text-primary hover:underline"
              aria-label={controlName("Add score pattern")}
              onClick={() => {
                const scores = [...((params.scores as number[][]) ?? [[2, 3]]), [0, 0]];
                setParam("scores", scores);
              }}
            >
              <Plus className="h-3 w-3" aria-hidden />
              Add score pattern
            </button>
          </div>
        </>
      )}
      {/* ── match_mvp_check: stat + top_n + team count in top ── */}
      {conditionType === "match_mvp_check" && (
        <>
          <div className="flex gap-1">
            <Select value={(params.stat as string) ?? "Performance"} onValueChange={(v) => setParam("stat", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Stat")}><SelectValue placeholder="Stat…" /></SelectTrigger>
              <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={(params.sort_order as string) ?? "auto"} onValueChange={(v) => setParam("sort_order", v)}>
              <SelectTrigger className="h-7 text-xs w-20" aria-label={controlName("Sort order")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto</SelectItem>
                <SelectItem value="desc">Desc</SelectItem>
                <SelectItem value="asc">Asc</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-1 items-center">
            <p className="text-muted-foreground text-xs shrink-0">Top</p>
            <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName("Top N players")} min={1} value={(params.top_n as number) ?? 3} onValueChange={(next) => setParam("top_n", next ?? 3)} />
            <p className="text-muted-foreground text-xs shrink-0">team in top</p>
            <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Teammates in top operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName("Teammates in top")} min={0} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
          </div>
        </>
      )}
      {/* ── bracket_path: lower/upper bracket + options ── */}
      {conditionType === "bracket_path" && (
        <>
          <div className="flex gap-1">
            <Select
              value={params.played_upper_bracket === true ? "upper" : "lower"}
              onValueChange={(v) => {
                if (v === "upper") {
                  setParam("played_lower_bracket", undefined);
                  setParam("played_upper_bracket", true);
                } else {
                  setParam("played_lower_bracket", true);
                  setParam("played_upper_bracket", undefined);
                }
              }}
            >
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Bracket path")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="lower">Lower bracket</SelectItem>
                <SelectItem value="upper">Upper bracket only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {(params.played_lower_bracket ?? true) && (
            <>
              <div className="flex gap-1 items-center">
                <p className="text-muted-foreground text-xs shrink-0">Min LB wins</p>
                <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Minimum lower-bracket wins")} value={(params.min_lower_bracket_wins as number) ?? null} placeholder="Any" onValueChange={(next) => setParam("min_lower_bracket_wins", next ?? undefined)} />
              </div>
              <div className="flex gap-1 items-center">
                <p className="text-muted-foreground text-xs shrink-0">Lost in round</p>
                <Select value={lostInRoundOp ?? "any"} onValueChange={(v) => setParam("lost_in_round", v !== "any" ? { op: v, value: lostInRoundValue } : undefined)}>
                  <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Lost-in-round operator")}><SelectValue placeholder="Any" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">Any</SelectItem>
                    {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                  </SelectContent>
                </Select>
                {lostInRoundOp && (
                  <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Lost-in-round number")} value={lostInRoundValue} onValueChange={(next) => setParam("lost_in_round", { ...lostInRound, value: next ?? 1 })} />
                )}
              </div>
            </>
          )}
        </>
      )}
      {/* ── tournament_format: double_elim / single_elim / round_robin ── */}
      {conditionType === "tournament_format" && (
        <Select value={(params.format as string) ?? "double_elim"} onValueChange={(v) => setParam("format", v)}>
          <SelectTrigger className="h-7 text-xs" aria-label={controlName("Tournament format")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="double_elim">Double elimination</SelectItem>
            <SelectItem value="single_elim">Single elimination</SelectItem>
            <SelectItem value="round_robin">Round robin</SelectItem>
            <SelectItem value="has_bracket">Any bracket</SelectItem>
          </SelectContent>
        </Select>
      )}
      {/* ── distinct_count: field + op + value + scope + min_playtime ── */}
      {conditionType === "distinct_count" && (
        <>
          <div className="flex gap-1">
            <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="role">Role</SelectItem>
                <SelectItem value="hero">Hero</SelectItem>
                <SelectItem value="match">Match</SelectItem>
              </SelectContent>
            </Select>
            <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs w-16" aria-label={controlName("Distinct count")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
          </div>
          <div className="flex gap-1">
            <Select value={(params.scope as string) ?? "global"} onValueChange={(v) => setParam("scope", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Counting scope")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="global">Global</SelectItem>
                <SelectItem value="tournament">Per tournament</SelectItem>
              </SelectContent>
            </Select>
            {(params.field as string) === "hero" && (
              <NumberInput integer className="h-7 text-xs w-20" aria-label={controlName("Minimum hero playtime in seconds")} placeholder="Min time (s)" value={(params.min_playtime as number) ?? null} onValueChange={(next) => setParam("min_playtime", next ?? undefined)} />
            )}
          </div>
        </>
      )}
      {conditionType === "stable_streak" && (
        <>
          <div className="space-y-1">
            <p className="text-muted-foreground" id={`${nodeId}-streak-fields`}>Fields</p>
            <div className="flex flex-wrap gap-1" role="group" aria-labelledby={`${nodeId}-streak-fields`}>
              {["role", "division", "team", "hero"].map((f) => {
                const fields = (params.fields as string[]) ?? [];
                const active = fields.includes(f);
                return (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={active}
                    aria-label={controlName(`Track ${f}`)}
                    className={`px-1.5 py-0.5 rounded text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "bg-muted border-border hover:bg-accent"}`}
                    onClick={() => {
                      const next = active ? fields.filter((x) => x !== f) : [...fields, f];
                      setParam("fields", next);
                    }}
                  >
                    {f}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="flex gap-1 items-center">
            <p className="text-muted-foreground shrink-0">Min streak</p>
            <NumberInput integer className="h-7 text-xs w-16" aria-label={controlName("Minimum streak")} min={2} value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
          </div>
        </>
      )}
      {["match_win", "is_captain", "encounter_revenge"].includes(conditionType ?? "") && (
        <p className="text-muted-foreground italic">No parameters</p>
      )}
    </div>
  );
}
