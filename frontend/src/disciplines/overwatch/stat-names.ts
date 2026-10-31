export enum LogStatsName {
  Eliminations = "eliminations",
  FinalBlows = "final_blows",
  Deaths = "deaths",
  AllDamageDealt = "all_damage_dealt",
  BarrierDamageDealt = "barrier_damage_dealt",
  HeroDamageDealt = "hero_damage_dealt",
  HealingDealt = "healing_dealt",
  HealingReceived = "healing_received",
  SelfHealing = "self_healing",
  DamageTaken = "damage_taken",
  DamageBlocked = "damage_blocked",
  DefensiveAssists = "defensive_assists",
  OffensiveAssists = "offensive_assists",
  UltimatesEarned = "ultimates_earned",
  UltimatesUsed = "ultimates_used",
  MultikillBest = "multikill_best",
  Multikills = "multikills",
  SoloKills = "solo_kills",
  ObjectiveKills = "objective_kills",
  EnvironmentalKills = "environmental_kills",
  EnvironmentalDeaths = "environmental_deaths",
  CriticalHits = "critical_hits",
  CriticalHitAccuracy = "critical_hit_accuracy",
  ScopedAccuracy = "scoped_accuracy",
  ScopedCriticalHitAccuracy = "scoped_critical_hit_accuracy",
  ScopedCriticalHitKills = "scoped_critical_hit_kills",
  ShotsFired = "shots_fired",
  ShotsHit = "shots_hit",
  ShotsMissed = "shots_missed",
  ScopedShotsFired = "scoped_shots_fired",
  ScopedShotsHit = "scoped_shots_hit",
  WeaponAccuracy = "weapon_accuracy",
  HeroTimePlayed = "hero_time_played",

  // Derived from kill_feed (parser writes them like any other stat).
  FirstPicks = "first_picks",
  FirstDeaths = "first_deaths",
  UltimateKills = "ultimate_kills",
  SupportKills = "support_kills",

  OverperformanceBadge = "overperformance_badge",

  // Per-feature impact contributions (segment 0 only), one per backend `IMPACT_FEATURES` entry.
  ContribEliminations = "contrib_eliminations",
  ContribFinalBlows = "contrib_final_blows",
  ContribDeaths = "contrib_deaths",
  ContribHeroDamageDealt = "contrib_hero_damage_dealt",
  ContribHealingDealt = "contrib_healing_dealt",
  ContribDamageBlocked = "contrib_damage_blocked",
  ContribDamageTaken = "contrib_damage_taken",
  ContribBarrierDamageDealt = "contrib_barrier_damage_dealt",
  ContribOffensiveAssists = "contrib_offensive_assists",
  ContribDefensiveAssists = "contrib_defensive_assists",
  ContribUltimatesEarned = "contrib_ultimates_earned",
  ContribUltimatesUsed = "contrib_ultimates_used",
  ContribMultikills = "contrib_multikills",
  ContribSoloKills = "contrib_solo_kills",
  ContribObjectiveKills = "contrib_objective_kills",
  ContribEnvironmentalKills = "contrib_environmental_kills",
  ContribFirstPicks = "contrib_first_picks",
  ContribFirstDeaths = "contrib_first_deaths",
  ContribUltimateKills = "contrib_ultimate_kills",
  ContribSupportKills = "contrib_support_kills",

  KD = "kd",
  KDA = "kda",
  DamageDelta = "damage_delta",
  FBE = "fbe",
  DamageFB = "damage_fb",
  Assists = "assists",
  ImpactPoints = "impact_points",
  ImpactRank = "impact_rank",
  OverperformanceScore = "overperformance_score",

  Winrate = "winrate"
}

/** A stat code as a label (`hero_damage_dealt` → `Hero damage dealt`). */
export const getHumanizedStats = (stats: LogStatsName) => {
  return stats
    .replace(/^[\s_]+|[\s_]+$/g, "")
    .replace(/[_\s]+/g, " ")
    .replace(/^[a-z]/, function (m) {
      return m.toUpperCase();
    });
};
