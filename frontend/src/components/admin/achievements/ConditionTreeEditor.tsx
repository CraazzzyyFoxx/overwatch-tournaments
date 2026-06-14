"use client";

import { useState } from "react";
import { Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// --- Condition type definitions for the UI ---

const CONDITION_TYPES = [
  { value: "stat_threshold", label: "Stat Threshold", grain: "match", params: ["stat", "op", "value"] },
  { value: "match_criteria", label: "Match Criteria", grain: "match", params: ["field", "op", "value"] },
  { value: "match_win", label: "Match Win", grain: "match", params: [] },
  { value: "hero_stat", label: "Hero Stat", grain: "match", params: ["hero_slug", "stat", "op", "value"] },
  { value: "standing_position", label: "Standing Position", grain: "tournament", params: ["op", "value"] },
  { value: "standing_record", label: "Standing Record", grain: "tournament", params: ["field", "op", "value"] },
  { value: "div_change", label: "Division Change", grain: "tournament", params: ["direction", "min_shift"] },
  { value: "div_level", label: "Division Level", grain: "tournament", params: ["op", "value"] },
  { value: "is_captain", label: "Is Captain", grain: "tournament", params: [] },
  { value: "is_newcomer", label: "Is Newcomer", grain: "tournament", params: [] },
  { value: "tournament_type", label: "Tournament Type", grain: "tournament", params: ["is_league"] },
  { value: "hero_kd_best", label: "Hero K/D Best", grain: "tournament", params: ["hero_slug", "min_time", "min_matches"] },
  { value: "team_players_match", label: "Team Players Match", grain: "tournament", params: ["mode", "condition"] },
  { value: "captain_property", label: "Captain Property", grain: "tournament", params: ["condition"] },
  { value: "player_role", label: "Player Role", grain: "subcondition", params: ["role"] },
  { value: "player_sub_role", label: "Player Sub-role", grain: "subcondition", params: ["sub_role"] },
  { value: "player_div", label: "Player Division", grain: "subcondition", params: ["op", "value"] },
  { value: "player_flag", label: "Player Flag (Legacy)", grain: "subcondition", params: ["flag"] },
  { value: "encounter_score", label: "Encounter Score", grain: "tournament", params: ["round_type", "scores"] },
  { value: "encounter_revenge", label: "Encounter Revenge", grain: "tournament", params: [] },
  { value: "global_stat_sum", label: "Global Stat Sum", grain: "global", params: ["stat", "op", "value"] },
  { value: "tournament_count", label: "Tournament Count", grain: "global", params: ["op", "value"] },
  { value: "global_winrate", label: "Global Winrate", grain: "global", params: ["order", "limit"] },
  { value: "distinct_count", label: "Distinct Count", grain: "global", params: ["field", "op", "value", "scope"] },
  { value: "consecutive", label: "Consecutive", grain: "global", params: ["metric", "min_streak"] },
  { value: "stable_streak", label: "Stable Streak", grain: "global", params: ["fields", "min_streak"] },
] as const;

const OPERATORS = ["==", "!=", ">=", ">", "<=", "<"];

const STATS = [
  "Eliminations", "FinalBlows", "Deaths", "AllDamageDealt", "HeroDamageDealt",
  "HealingDealt", "DamageTaken", "DamageBlocked", "EnvironmentalKills",
  "EnvironmentalDeaths", "ScopedCriticalHitKills", "SoloKills", "CriticalHits",
  "HeroTimePlayed", "UltimatesEarned", "Performance", "KD", "KDA",
];

interface ConditionTreeEditorProps {
  value: Record<string, unknown>;
  onChange: (tree: Record<string, unknown>) => void;
}

export function ConditionTreeEditor({ value, onChange }: ConditionTreeEditorProps) {
  return (
    <div className="space-y-2">
      <Label>Condition Tree</Label>
      <ConditionNode
        node={value}
        onChange={onChange}
        onRemove={undefined}
        depth={0}
      />
    </div>
  );
}

// --- Recursive condition node ---

interface ConditionNodeProps {
  node: Record<string, unknown>;
  onChange: (node: Record<string, unknown>) => void;
  onRemove: (() => void) | undefined;
  depth: number;
}

function ConditionNode({ node, onChange, onRemove, depth }: ConditionNodeProps) {
  const [collapsed, setCollapsed] = useState(false);

  const isAnd = "AND" in node;
  const isOr = "OR" in node;
  const isNot = "NOT" in node;
  const isLogical = isAnd || isOr || isNot;
  const logicalKey = isAnd ? "AND" : isOr ? "OR" : isNot ? "NOT" : null;

  if (isNot) {
    const child = node["NOT"] as Record<string, unknown>;
    return (
      <Card className={`border-red-200 dark:border-red-800 ${depth > 0 ? "ml-4" : ""}`}>
        <CardContent className="pt-3 pb-3 space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant="destructive">NOT</Badge>
            <div className="flex-1" />
            <Button variant="ghost" size="sm" onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange({ type: "match_win" })}
            >
              Switch to Leaf
            </Button>
            {onRemove && (
              <Button variant="ghost" size="icon" onClick={onRemove}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            )}
          </div>
          {!collapsed && (
            <ConditionNode
              node={child}
              onChange={(updated) => onChange({ NOT: updated })}
              onRemove={undefined}
              depth={depth + 1}
            />
          )}
        </CardContent>
      </Card>
    );
  }

  if (isLogical && logicalKey) {
    const children = (node[logicalKey] as Record<string, unknown>[]) || [];

    return (
      <Card className={`${logicalKey === "AND" ? "border-blue-200 dark:border-blue-800" : "border-amber-200 dark:border-amber-800"} ${depth > 0 ? "ml-4" : ""}`}>
        <CardContent className="pt-3 pb-3 space-y-2">
          <div className="flex items-center gap-2">
            <Select
              value={logicalKey}
              onValueChange={(val) => {
                const newNode: Record<string, unknown> = {};
                newNode[val] = children;
                onChange(newNode);
              }}
            >
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="AND">AND</SelectItem>
                <SelectItem value="OR">OR</SelectItem>
              </SelectContent>
            </Select>
            <Badge variant="outline">{children.length} conditions</Badge>
            <div className="flex-1" />
            <Button variant="ghost" size="sm" onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
            {onRemove && (
              <Button variant="ghost" size="icon" onClick={onRemove}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            )}
          </div>
          {!collapsed && (
            <>
              {children.map((child, i) => (
                <ConditionNode
                  key={i}
                  node={child}
                  onChange={(updated) => {
                    const newChildren = [...children];
                    newChildren[i] = updated;
                    onChange({ [logicalKey]: newChildren });
                  }}
                  onRemove={() => {
                    const newChildren = children.filter((_, idx) => idx !== i);
                    if (newChildren.length === 0) {
                      onChange({ type: "match_win" });
                    } else {
                      onChange({ [logicalKey]: newChildren });
                    }
                  }}
                  depth={depth + 1}
                />
              ))}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onChange({ [logicalKey]: [...children, { type: "match_win" }] })}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Condition
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onChange({ [logicalKey]: [...children, { AND: [] }] })}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Group
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onChange({ [logicalKey]: [...children, { NOT: { type: "match_win" } }] })}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add NOT
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    );
  }

  // Leaf condition
  return <LeafConditionEditor node={node} onChange={onChange} onRemove={onRemove} depth={depth} />;
}

// --- Leaf condition editor ---

interface LeafEditorProps {
  node: Record<string, unknown>;
  onChange: (node: Record<string, unknown>) => void;
  onRemove: (() => void) | undefined;
  depth: number;
}

function LeafConditionEditor({ node, onChange, onRemove, depth }: LeafEditorProps) {
  const condType = (node.type as string) || "";
  const params = (node.params as Record<string, unknown>) || {};

  const setParam = (key: string, value: unknown) => {
    onChange({ ...node, params: { ...params, [key]: value } });
  };

  return (
    <Card className={`border-green-200 dark:border-green-800 ${depth > 0 ? "ml-4" : ""}`}>
      <CardContent className="pt-3 pb-3">
        <div className="flex items-start gap-2">
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-2">
              <Select
                value={condType}
                onValueChange={(val) => onChange({ type: val, params: {} })}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder="Condition type..." />
                </SelectTrigger>
                <SelectContent>
                  {CONDITION_TYPES.map((ct) => (
                    <SelectItem key={ct.value} value={ct.value}>
                      {ct.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Badge variant="secondary">
                {CONDITION_TYPES.find((ct) => ct.value === condType)?.grain ?? "?"}
              </Badge>
              <div className="flex-1" />
              <Button
                variant="outline"
                size="sm"
                onClick={() => onChange({ AND: [node, { type: "match_win" }] })}
              >
                Wrap in AND
              </Button>
              {onRemove && (
                <Button variant="ghost" size="icon" onClick={onRemove}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              )}
            </div>

            {/* Dynamic param editors based on condition type */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {(condType === "stat_threshold" || condType === "global_stat_sum") && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Stat</Label>
                    <Select value={(params.stat as string) ?? ""} onValueChange={(v) => setParam("stat", v)}>
                      <SelectTrigger><SelectValue placeholder="Stat..." /></SelectTrigger>
                      <SelectContent>
                        {STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Operator</Label>
                    <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Value</Label>
                    <Input
                      type="number"
                      value={(params.value as number) ?? 0}
                      onChange={(e) => setParam("value", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "match_criteria" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Field</Label>
                    <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
                      <SelectTrigger><SelectValue placeholder="Field..." /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="closeness">Closeness</SelectItem>
                        <SelectItem value="match_time">Match Time</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Operator</Label>
                    <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Value</Label>
                    <Input
                      type="number"
                      value={(params.value as number) ?? 0}
                      onChange={(e) => setParam("value", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {(condType === "standing_position" || condType === "tournament_count") && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Operator</Label>
                    <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Value</Label>
                    <Input
                      type="number"
                      value={(params.value as number) ?? 1}
                      onChange={(e) => setParam("value", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "div_change" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Direction</Label>
                    <Select value={(params.direction as string) ?? "up"} onValueChange={(v) => setParam("direction", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="up">Up</SelectItem>
                        <SelectItem value="down">Down</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Min Shift</Label>
                    <Input
                      type="number"
                      value={(params.min_shift as number) ?? 1}
                      onChange={(e) => setParam("min_shift", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "hero_kd_best" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Hero Slug</Label>
                    <Input
                      value={(params.hero_slug as string) ?? ""}
                      onChange={(e) => setParam("hero_slug", e.target.value)}
                      placeholder="e.g. dva"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Min Time (sec)</Label>
                    <Input
                      type="number"
                      value={(params.min_time as number) ?? 600}
                      onChange={(e) => setParam("min_time", Number(e.target.value))}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Min Matches</Label>
                    <Input
                      type="number"
                      value={(params.min_matches as number) ?? 3}
                      onChange={(e) => setParam("min_matches", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "player_role" && (
                <div className="space-y-1">
                  <Label className="text-xs">Role</Label>
                  <Select value={(params.role as string) ?? "Damage"} onValueChange={(v) => setParam("role", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Tank">Tank</SelectItem>
                      <SelectItem value="Damage">Damage</SelectItem>
                      <SelectItem value="Support">Support</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}

              {condType === "player_sub_role" && (
                <div className="space-y-1">
                  <Label className="text-xs">Sub-role</Label>
                  <Input
                    value={(params.sub_role as string) ?? ""}
                    onChange={(e) => setParam("sub_role", e.target.value)}
                    placeholder="e.g. hitscan"
                  />
                </div>
              )}

              {condType === "player_flag" && (
                <div className="space-y-1">
                  <Label className="text-xs">Flag</Label>
                  <Select value={(params.flag as string) ?? "primary"} onValueChange={(v) => setParam("flag", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="primary">Primary</SelectItem>
                      <SelectItem value="secondary">Secondary</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}

              {condType === "player_div" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Operator</Label>
                    <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Value</Label>
                    <Input
                      type="number"
                      value={(params.value as number) ?? 1}
                      onChange={(e) => setParam("value", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "tournament_type" && (
                <div className="space-y-1">
                  <Label className="text-xs">Is League</Label>
                  <Select
                    value={String(params.is_league ?? false)}
                    onValueChange={(v) => setParam("is_league", v === "true")}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">Yes</SelectItem>
                      <SelectItem value="false">No</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}

              {condType === "global_winrate" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Order</Label>
                    <Select value={(params.order as string) ?? "desc"} onValueChange={(v) => setParam("order", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="desc">Top (desc)</SelectItem>
                        <SelectItem value="asc">Bottom (asc)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Limit</Label>
                    <Input
                      type="number"
                      value={(params.limit as number) ?? 20}
                      onChange={(e) => setParam("limit", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "consecutive" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Metric</Label>
                    <Select value={(params.metric as string) ?? "win"} onValueChange={(v) => setParam("metric", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="win">Win</SelectItem>
                        <SelectItem value="day_two">Day Two</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Min Streak</Label>
                    <Input
                      type="number"
                      value={(params.min_streak as number) ?? 2}
                      onChange={(e) => setParam("min_streak", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "distinct_count" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Field</Label>
                    <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
                      <SelectTrigger><SelectValue placeholder="Field..." /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="role">Role</SelectItem>
                        <SelectItem value="hero">Hero</SelectItem>
                        <SelectItem value="match">Match</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Operator</Label>
                    <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Value</Label>
                    <Input
                      type="number"
                      value={(params.value as number) ?? 1}
                      onChange={(e) => setParam("value", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {condType === "stable_streak" && (
                <>
                  <div className="space-y-1 col-span-full">
                    <Label className="text-xs">Fields</Label>
                    <div className="flex flex-wrap gap-1">
                      {["role", "division", "team", "hero"].map((f) => {
                        const fields = (params.fields as string[]) ?? [];
                        const active = fields.includes(f);
                        return (
                          <button
                            key={f}
                            type="button"
                            className={`px-2 py-0.5 rounded text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "bg-muted border-border hover:bg-accent"}`}
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
                  <div className="space-y-1">
                    <Label className="text-xs">Min Streak</Label>
                    <Input
                      type="number"
                      min={2}
                      value={(params.min_streak as number) ?? 2}
                      onChange={(e) => setParam("min_streak", Number(e.target.value))}
                    />
                  </div>
                </>
              )}

              {/* No params needed for: match_win, is_captain, is_newcomer, encounter_revenge */}
              {["match_win", "is_captain", "is_newcomer", "encounter_revenge"].includes(condType) && (
                <p className="text-xs text-muted-foreground col-span-full">No parameters required</p>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
