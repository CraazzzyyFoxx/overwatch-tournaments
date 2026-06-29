export const en = {
  common: {
    draft: "Draft",
    back: "Back",
    cancel: "Cancel",
    next: "Next",
    submit: "Submit",
    loading: "Loading...",
    error: "Error",
    registered: "registered",
    players: "players",
    inTeams: "in teams",
    rostered: "Rostered",
    done: "done",
    format: "Format",
    stages: "Stages",
    teams: "Teams",
    participants: "Participants",
    matches: "Matches",
    heroes: "Heroes",
    standings: "Standings",
    bracket: "Bracket",
    rolesList: "Roles",
    ranks: "Ranks",
    bracketInstructions: "Drag to pan the bracket / Press Esc to exit",
    bracketFullscreen: "Fullscreen",
    bracketExitFullscreen: "Exit fullscreen (Esc)",
    profile: "Profile",
    accountSettings: "Account settings",
    logout: "Logout",
    language: "Language",
    noTeams: "No teams to show.",
    noParticipants: "No participants found.",
    noStandings: "No standings available yet.",
    noMatches: "No matches found for {stage}",
    noStages: "No stages configured for this tournament",
    noBracketMatches: "No bracket matches found for the selected stage",
    noHeroData: "No hero data yet.",
    playtimeLabel: "% playtime",
    teamsCount: "{count} teams",
    roundRobin: "round-robin",
    swiss: "swiss",
    byPlaytime: "By play time",
    byPlacement: "By placement",
    byAvgSr: "By avg SR",
    byName: "By name",
    all: "All",
    group: "Group",
    groups: "Groups",
    playoff: "Playoff",
    playoffStandings: "Playoff standings",
    topAdvance: "TOP {count} ADVANCE",
    buchholz: "Buchholz",
    headToHead: "Head-to-Head",
    scoreDiff: "Score differential",
    tiebreakers: "Tiebreakers",
    tiebreakerMetrics: {
      points: "Points",
      match_wins: "Match wins",
      head_to_head: "Head-to-Head",
      median_buchholz: "Median Buchholz",
      buchholz: "Buchholz",
      score_differential: "Score differential",
      manual_override: "Manual override"
    },
    combined: "Combined",
    groupStage: "Group stage",
    confirmCheckIn: "Confirm check-in?",
    checkInDesc: "This will mark you as checked in for the tournament. Confirm only if you are ready to participate.",
    withdrawReg: "Withdraw registration?",
    withdrawDesc: "Your application will be marked as withdrawn, and you will not be able to register for this tournament again.",
    confirmWithdraw: "Confirm withdraw",
    checkingIn: "Checking in...",
    withdrawing: "Withdrawing...",
    checkIn: "Check-in",
    withdraw: "Withdraw",
    yourRegistration: "Your registration",
    pendingReview: "Pending review",
    approved: "Approved",
    rejected: "Rejected",
    withdrawn: "Withdrawn",
    banned: "Banned",
    incomplete: "Incomplete",
    searchParticipants: "Search participants...",
    columns: "Columns",
    reset: "Reset",
    more: "more",
    smurfBattleTags: "Smurf BattleTags",
    smurfDesc: "All registered smurf BattleTags for this participant.",
    history: "History",
    status: "Status",
    balancer: "Balancer",
    admission: "Admission",
    admissionStatus: {
      admitted: "Admitted",
      notAdmitted: "Not Admitted",
      pendingCheckIn: "Admitted (Check-in pending)"
    },
    yes: "Yes",
    no: "No",
    noAccess: "No access",
    notCaptain: "You are not the captain of this team",
    roleVerificationFailed: "Failed to verify role",
    tournamentNotFound: "Tournament not found.",
    tournaments: "Tournaments",
    league: "League",
    formatLabel: {
      groupsPlayoff: "Groups → Playoff",
      playoffBracket: "Playoff bracket",
      groupStage: "Group stage"
    },
    statusBadge: {
      draft: "Draft",
      registration: "Registration",
      check_in: "Check-in",
      live: "Live",
      playoffs: "Playoffs",
      completed: "Completed",
      archived: "Archived"
    },
    roles: {
      tank: "Tank",
      dps: "DPS",
      support: "Support",
      flex: "Flex"
    },
    subroles: {
      hitscan: "Hitscan",
      projectile: "Projectile",
      main_heal: "Main Heal",
      light_heal: "Light Heal",
      main_tank: "Main Tank",
      off_tank: "Off Tank",
      flanker: "Flanker",
      flex_dps: "Flex DPS",
      flex_support: "Flex Support"
    },
    subrolesShort: {
      hitscan: "HS",
      projectile: "PROJ",
      main_heal: "MH",
      light_heal: "LH",
      main_tank: "MT",
      off_tank: "OT",
      flanker: "FLK",
      flex_dps: "FD",
      flex_support: "FS"
    }
  },
  registration: {
    wizard: {
      title: "Register",
      titleFor: "Register for {name}",
      step1Desc: "Step 1 - Verify your game accounts.",
      step2Desc: "Step 2 - Pick your preferred role.",
      step3Desc: "Step 3 - Any additional info for organizers.",
      steps: {
        accounts: "Accounts",
        roles: "Roles",
        details: "Details"
      },
      validation: {
        battleTagRequired: "BattleTag is required.",
        smurfTagsRequired: "Add at least one smurf account.",
        discordRequired: "Discord is required.",
        twitchRequired: "Twitch is required.",
        primaryRoleRequired: "Choose a primary role or enable Flex before continuing.",
        fallbackRoleRequired: "This tournament requires at least one fallback role.",
        topHeroesRequired: "Select at least one top hero before continuing.",
        notesRequired: "Notes are required.",
        fieldRequired: "Fill in the required field: {label}.",
        invalidFormat: "{label} format is invalid.",
        verifiedNoAccount: "Link a verified {label} account via OAuth to register.",
        verifiedRequired: "Select your verified {label} account.",
        verifiedMismatch: "{label} must match an OAuth-verified account on your profile."
      }
    },
    accounts: {
      title: "Your Accounts",
      desc: "We've pre-filled your linked accounts. Change them if needed.",
      battleTag: "BattleTag",
      smurfs: "Smurf Accounts",
      discord: "Discord",
      twitch: "Twitch",
      addSmurfPlaceholder: "Add smurf BattleTag",
      addSmurfButton: "Add",
      verifiedHint: "Choose one of your OAuth-verified accounts.",
      verifiedNone: "No verified {label} account is linked.",
      verifiedLink: "Link {label} via OAuth"
    },
    roles: {
      title: "Choose Your Role",
      desc: "Set your primary role first. Then choose secondary roles we can assign you to if a team is short on them during balancing.",
      primary: {
        title: "Primary Role",
        desc: "This is the role we should place you on by default."
      },
      secondary: {
        title: "Secondary Roles",
        required: "Required",
        optional: "Optional",
        clearAll: "Clear all",
        selectAll: "Select all",
        descEmptyPrimary: "Pick a primary role first to reveal your fallback role options.",
        descFlex: "Flex already covers all roles, so no fallback roles are needed.",
        descFallback: "These are fallback roles. If a team is missing one of them, we may place you there during balancing.",
        emptyStateFlex: "Flex already covers every role, so fallback roles are not needed for this registration.",
        emptyStateChoosePrimary: "Choose a primary role first. We will then show the two fallback roles you can also be assigned to."
      },
      flex: {
        title: "Flex",
        desc: "All roles, equal priority"
      },
      specialization: "Specialization",
      roleSpecialization: "{role} specialization",
      any: "Any",
      topHeroes: {
        title: "Top Heroes",
        desc: "Pick up to {max} hero(es) you play best for each role.",
        anyRole: "Any role",
        count: "{count}/{max}"
      }
    },
    details: {
      title: "Additional Details",
      descWithFields: "Almost done! Fill in any extra info.",
      descNoFields: "No additional fields required. You're ready to submit!",
      streamPov: "Stream POV",
      streamPovLabel: "I will stream my POV",
      notes: "Notes",
      notesPlaceholder: "Anything you'd like organizers to know"
    },
    button: {
      closed: "Registration closed",
      loginToRegister: "Login to register",
      register: "Register"
    },
    myCard: {
      title: "Your Registration",
      status: "Status",
      checkInStatus: "Check-in",
      checkedIn: "Checked In",
      checkInRequired: "Required",
      checkInNotStarted: "Pending",
      checkInClosed: "Closed",
      primaryRole: "Primary Role",
      secondaryRoles: "Secondary Roles",
      noSecondaryRoles: "No fallback roles",
      accounts: "Linked Accounts",
      details: "Additional Details",
      streamPovActive: "Will stream POV",
      streamPovInactive: "Won't stream POV",
      noNotes: "No notes provided",
      checkInSuccess: "You have confirmed your participation!",
      pendingCheckInDesc: "Registration approved. Check-in will start later.",
      pendingReviewDesc: "The application is currently under review by the tournament organizers.",
      showDetails: "Show details",
      hideDetails: "Hide details"
    }
  },
  draft: {
    loading: "Loading draft…",
    notYourPick: "Wait for your turn to pick",
    round: "Round",
    pick: "Pick",
    onTheClock: "On the clock",
    state: {
      setup: "Setup",
      ready: "Ready",
      live: "Live",
      paused: "Paused",
      completed: "Completed",
      cancelled: "Cancelled"
    },
    empty: {
      title: "No draft yet",
      body: "The draft hasn’t been set up for this tournament."
    },
    roster: { empty: "Empty" },
    pool: { title: "Available players", empty: "No available players" },
    actions: { confirm: "Confirm pick" },
    admin: {
      start: "Start draft",
      pause: "Pause",
      resume: "Resume",
      rollback: "Rollback last pick",
      cancel: "Cancel draft",
      export: "Export to teams"
    },
    bottomPanel: {
      readyToPick: "Ready to pick",
      yourTurn: "Your turn to pick",
      selectPlayer: "Select a player",
      selectPrompt: "Select a player from the pool below to prepare your pick",
      waitingTurn: "Waiting for turn",
      yourTurnIn: "Your turn in {count} pick(s)",
      allPicksDone: "All your picks completed",
      liveDraft: "Live Draft",
      currentlyPicking: "Currently picking",
      draftPaused: "Draft paused",
      draftCompleted: "Draft completed",
      draftCancelled: "Draft cancelled",
      waitingStart: "Waiting for start"
    },
    presence: {
      title: "Captains • {online} of {total} online",
      watching: "{count} watching",
      offline: "offline"
    }
  },
  matchEdit: {
    title: "Edit Match",
    pendingConfirmation: "Pending Confirmation",
    disputed: "Disputed",
    matchScore: "Match score",
    manualEntry: "Manual result entry",
    resultPresets: "Result presets",
    status: "Status",
    matchCloseness: "Match closeness",
    closenessHint: "Only the overall score is edited. Maps will appear after parsing the log files.",
    cancel: "Cancel",
    save: "Save",
    confirming: "Confirming...",
    confirmResult: "Confirm Result",
    saving: "Saving...",
    negativeScoreError: "Match score cannot be negative",
    matchUpdated: "Match updated",
    resultConfirmed: "Result confirmed",
    saveError: "Error",
    saveErrorMessage: "Failed to save",
    confirmErrorMessage: "Failed to confirm",
    presetDescriptions: {
      "Home sweep": "Home sweep",
      "Home close win": "Home close win",
      "Draw": "Draw",
      "Away close win": "Away close win",
      "Away sweep": "Away sweep"
    }
  },
  matchReport: {
    title: "Match Report",
    quickResult: "Quick result",
    matchQuality: "Match quality",
    howClose: "How close was the series",
    submit: "Submit",
    submitting: "Submitting...",
    submittedForConfirmation: "Result submitted for confirmation",
    submitErrorMessage: "Failed to submit",
    qualityDescriptions: {
      1: "One-sided match",
      2: "Almost one-sided",
      3: "Weak resistance",
      4: "Average match",
      5: "Even game",
      6: "Slight edge",
      7: "Good fight",
      8: "Very close",
      9: "Intense struggle",
      10: "To the last breath"
    },
    qualityLegend: {
      oneSided: "1 - one-sided match",
      toTheEnd: "10 - to the end"
    }
  },
  rankAutofill: {
    title: "Rank autofill",
    subtitle: "Configure the source chain and pick exactly which players to update.",
    backToRegistrations: "Back to registrations",
    chainTitle: "Source chain",
    chainDescription:
      "Drag to set priority order, disable sources you don't need, and optionally limit recency (tournaments for history/analytics, days for OW).",
    toggleChainAria: "Toggle source chain",
    overwrite: "Overwrite existing",
    overwriteAria: "Overwrite existing ranks",
    addToBalancer: "Move eligible to balancer",
    addToBalancerAria: "Move eligible players to balancer",
    allowPartial: "Partial (fill found roles even if some are missing)",
    allowPartialAria: "Apply partially",
    previewUpdating: "Updating preview…",
    previewTitle: "Preview",
    previewDescription: "Priority fallback per role. Main BattleTag only.",
    searchPlaceholder: "Search players…",
    mismatchOnly: "Mismatches only",
    mismatchOnlyAria: "Show only players whose current rank differs from the suggestion",
    badgeMismatch: "mismatch",
    noMatches: "No players match the filters.",
    previewNotLoaded: "Preview not loaded.",
    previewErrorTitle: "Failed to load preview",
    previewErrorGeneric: "Request error",
    selectedCount: "Selected players: {count}",
    apply: "Apply to {count}",
    noTournamentTitle: "Select a tournament",
    noTournamentDescription: "Choose a tournament in the sidebar before configuring rank autofill.",
    successTitle: "Ranks autofilled",
    successDescription: "{applied} player(s), {roles} rank(s) updated. Skipped: {skipped}.",
    successBalancerSuffix: " {count} → balancer.",
    errorTitle: "Failed to autofill ranks",
    stats: {
      players: "Players",
      update: "Update",
      ranks: "Ranks",
      toBalancer: "→ Balancer",
      unverified: "Unverified",
      skipped: "Skipped"
    },
    sections: {
      assign: "To assign",
      skipped: "Skipped",
      alreadySet: "Already set"
    },
    selectAllAria: "Select all",
    selectAria: "Select {name}",
    dragAria: "Drag stage",
    enableAria: "Enable {label}",
    windowAria: "Window for {label}",
    noRanksToUpdate: "No ranks to update.",
    noneSkipped: "None skipped.",
    noUnchanged: "No unchanged registrations.",
    skippedFallback: "Skipped",
    unchangedFallback: "No changes needed.",
    badgePartial: "partial",
    badgeUnverified: "unverified",
    pillUnverified: "unverified",
    pillMissing: "missing",
    source: {
      ow: {
        label: "Overwatch rank",
        description: "Weekly composite of OW snapshots for the main BattleTag."
      },
      division_history: {
        label: "Balancer history",
        description: "Latest rank from past balancer registrations."
      },
      analytics: {
        label: "Analytics",
        description: "Latest rank from participation in past tournaments."
      }
    },
    window: {
      daysSuffix: "days",
      tournamentsSuffix: "tnmts",
      daysPlaceholder: "7",
      tournamentsPlaceholder: "all"
    }
  },
  analytics: {
    briefing: {
      eyebrow: "Tournament analytics",
      rankedBy: "ranked by {algorithm}",
      titleFallback: "Tournament analytics",
      pickPrompt: "Pick a tournament and an algorithm to see the briefing.",
      tournament: "Tournament",
      algorithm: "Algorithm",
      selectTournament: "Select a tournament",
      selectAlgorithm: "Select an algorithm",
      loadingTournaments: "Loading tournaments...",
      loadingAlgorithms: "Loading algorithms...",
      errorTournaments: "Failed to load tournaments",
      errorAlgorithms: "Failed to load algorithms"
    },
    verdict: {
      headline: "{teams} teams · {players} players",
      moves: "{count} likely division changes",
      flags: "{count} flags to review",
      misses: "{count} teams the forecast missed badly",
      newcomers: "{count} newcomers",
      forecast: "forecast off by ~{delta} places on average"
    },
    triage: {
      title: "Needs attention",
      allClear: "All clear — no flags, surprises or first-timers to look at.",
      flags: "Flags to review",
      misses: "Forecast misses",
      moves: "Likely division moves",
      newcomers: "First-timers",
      forecastFinished: "forecast {predicted} · finished {finished}",
      newPlayer: "new player",
      newRole: "new role"
    },
    standings: {
      title: "Standings",
      sortedBy: "{count} teams · sorted by {mode}",
      sortStandings: "Standings",
      sortPredicted: "By predicted",
      sortShift: "By shift",
      record: "record",
      confidence: "confidence",
      predicted: "Predicted {place}",
      predictedRange: "Predicted {mean} (p10–p90 {p10}–{p90})",
      manual: "manual",
      colRole: "Role",
      colBattleTag: "Battle tag",
      colCurrent: "Current",
      colForecast: "Forecast",
      colMove2: "Move 2",
      colMove1: "Move 1",
      colSignal: "Signal",
      colImpact: "Impact",
      colVsLocal: "vs similar",
      colConfidence: "Confidence",
      colManual: "Manual",
      colFlags: "Flags",
      editManualShift: "Edit manual shift",
      save: "Save changes"
    },
    forecast: {
      up: "Moving up",
      down: "Moving down",
      hold: "Holding",
      by: "by ~{magnitude} {unit}",
      confidence: "Confidence: {label}",
      confidenceWithPct: "Confidence: {label} ({pct}%)",
      divisionUnit: "div"
    },
    confidence: {
      high: "High",
      medium: "Medium",
      low: "Low"
    },
    organizer: {
      title: "Organizer tools",
      subtitle: "recalculate · train · manual edits"
    },
    deepDive: {
      title: "Deep dive",
      subtitle: "forecast horizon · standings odds · match quality"
    },
    page: {
      chooseParams: "Choose parameters",
      chooseParamsDesc: "Select a tournament and an algorithm to view analytics.",
      unavailable: "Analytics unavailable",
      unavailableDesc: "Failed to load analytics for the selected parameters.",
      noTeams: "No teams",
      noTeamsDesc: "No teams found for the selected tournament."
    },
    horizon: {
      title: "Predicted vs actual horizon",
      subtitle: "Open ring is predicted. Filled dot is actual placement.",
      predicted: "Predicted",
      actual: "Actual",
      predictedTip: "Predicted: {place}",
      actualTip: "Actual: {place}",
      deltaAvg: "Delta avg"
    },
    distribution: {
      title: "Predicted standings distribution",
      subtitle: "Monte Carlo simulation (5000 iter) over the calibrated pairwise win-probability model.",
      team: "Team",
      mean: "Mean (p10–p90)",
      top1: "P(top 1)",
      top3: "P(top 3)",
      top8: "P(top 8)",
      distribution: "Distribution",
      unavailable: "Standings v2 not available. Run the trainer first.",
      noData: "No predictions yet for this tournament."
    },
    matchQuality: {
      title: "Match quality & anomalies",
      subtitle: "Post-hoc per-encounter scoring (how close, how expected, how even) plus anomaly flags.",
      encounter: "Encounter #{id}",
      comp: "close",
      pred: "expected",
      skill: "even",
      unavailable: "Match Quality not available. Run the inference pipeline first.",
      noData: "No match-quality rows yet.",
      confirm: "Confirm — true positive",
      dismiss: "Dismiss — false positive"
    },
    anomalyLegend: {
      trigger: "What flags mean",
      title: "Anomaly flags",
      note: "Flags are review hints, not verdicts."
    },
    anomalyReason: {
      top_impact: "Among the strongest performers in their role",
      low_rank: "Registered at a low rank for results this strong",
      cohort_overperformance: "Outplayed others of the same role and division",
      strong_cohort_outlier: "Far above peers of the same role and division",
      raw_mvp_dominance: "Consistently tops the match scoreboard (MVP) for their rank",
      single_tournament_underperformance: "Played well below their level this tournament",
      sustained_underperformance: "Consistently below their level across recent tournaments",
      sharp_recent_drop: "A sharp drop from their usual results",
      mid_series_drop: "Results dropped sharply mid-series"
    },
    explanation: {
      trigger: "Why this score?",
      title: "What drove this score",
      subtitle: "The stats that pushed it above or below the average for this role.",
      raised: "raised",
      lowered: "lowered",
      loading: "Loading…",
      unavailable: "No explanation available yet."
    },
    features: {
      final_blows_p10: "Final blows / 10 min",
      hero_damage_p10: "Hero damage / 10 min",
      all_damage_p10: "All damage / 10 min",
      damage_blocked_p10: "Damage blocked / 10 min",
      damage_taken_p10: "Damage taken / 10 min",
      objective_kills_p10: "Objective kills / 10 min",
      solo_kills_p10: "Solo kills / 10 min",
      eliminations_p10: "Eliminations / 10 min",
      deaths_p10: "Deaths / 10 min",
      healing_p10: "Healing / 10 min",
      self_healing_p10: "Self-healing / 10 min",
      defensive_assists_p10: "Defensive assists / 10 min",
      offensive_assists_p10: "Offensive assists / 10 min",
      weapon_accuracy: "Weapon accuracy",
      critical_hit_accuracy: "Critical-hit accuracy",
      ult_economy: "Ult economy",
      mu_gap: "Skill gap vs opponent",
      opp_avg_mu: "Opponent strength",
      team_avg_mu: "Own team strength",
      rank: "Registration SR",
      won: "Won the map",
      score_delta: "Score margin",
      is_home: "Played at home",
      is_newcomer: "Newcomer",
      home_score: "Home score",
      away_score: "Away score"
    },
    glossary: {
      confidence: {
        label: "Confidence",
        plain: "How sure the model is about this forecast, based on how much history and match data it had."
      },
      shift: {
        label: "Division adjustment",
        plain: "Suggested change to a player's division for the next tournament (＋ moves up, − moves down)."
      },
      impact: {
        label: "Impact",
        plain: "How much better or worse the player did than expected for the match-up — 0–100 within their role."
      },
      vs_local: {
        label: "vs similar players",
        plain: "Performance compared to players of the same role and nearby division (0 = average, ＋ above, − below)."
      },
      points: {
        label: "Move signal",
        plain: "The raw signal driving the division forecast — the larger it is, the stronger the up/down push."
      },
      recent_moves: {
        label: "Recent moves",
        plain: "Division changes in the player's last two tournaments."
      },
      forecast_place: {
        label: "Forecast place",
        plain: "Where the model expects the team to finish."
      },
      likely_range: {
        label: "Likely finish",
        plain: "Where the team lands in 80% of simulated tournaments (10th–90th percentile)."
      },
      prob_top: {
        label: "Chance for top finish",
        plain: "Share of simulated tournaments where the team finished in the top N."
      },
      competitiveness: {
        label: "How close",
        plain: "How back-and-forth the match was — 100 is a nail-biter, 0 is a blowout."
      },
      predictability: {
        label: "How expected",
        plain: "How well the result matched the pre-match forecast — 100 means it went as expected."
      },
      skill_balance: {
        label: "How even",
        plain: "How evenly matched the two teams' ratings were — 100 is a perfectly even match-up."
      },
      match_quality: {
        label: "Match quality",
        plain: "Overall watchability: a blend of how close, how expected and how even the match was."
      },
      forecast_miss: {
        label: "Forecast miss",
        plain: "How far the forecast landed from the real finish, in places."
      },
      evidence: {
        label: "Evidence",
        plain: "Weighted amount of history behind the forecast — more evidence means more confidence."
      },
      newcomer: {
        label: "Newcomer",
        plain: "Playing their first tournament, or their first time in this role."
      },
      why_score: {
        label: "Why this score",
        plain: "The player stats that pushed the impact score up or down the most."
      },
      smurf: {
        label: "Possible smurf",
        plain: "Playing well above their division — could be a strong player on an under-ranked account."
      },
      throw: {
        label: "Possible throw",
        plain: "Looks like they stopped trying mid-series — play dropped sharply below their own usual level."
      },
      troll: {
        label: "Possible griefing",
        plain: "Repeatedly playing below their own level, dragging their team down."
      },
      sandbag: {
        label: "Possible sandbag",
        plain: "One unexpectedly weak tournament that stands out against the player's own track record."
      },
      reasonsLabel: "Why flagged",
      climbing: {
        label: "Climbing",
        plain: "Players the model thinks are playing above their division and should move up a tier."
      },
      dropping: {
        label: "Dropping",
        plain: "Players performing below their division — the model leans toward moving them down a tier."
      },
      watch: {
        label: "Watch flags",
        plain: "Automatic heads-ups when someone's results look unusual. A prompt for a human to look — never a verdict."
      },
      avg_confidence: {
        label: "Average confidence",
        plain: "How much data is behind the calls across the whole bracket. It climbs as more maps are played."
      },
      upsets: {
        label: "Upsets",
        plain: "Teams that finished four or more places away from their predicted spot — the bracket's biggest surprises."
      },
      new_faces: {
        label: "New faces",
        plain: "Players new to the tournament, or playing a role they haven't before. Their numbers carry less weight until we see more."
      },
      predicted_move: {
        label: "Predicted move",
        plain: "Whether the model thinks a player belongs in a higher (climb) or lower (drop) division than they're in now. Hold means they're right where they should be."
      },
      impact_percentile: {
        label: "Impact percentile",
        plain: "Where a player's impact ranks among others in the same role and division — 90 means they beat almost everyone at their level."
      }
    },
    hero: {
      idLine: "#{number} · {dates}",
      statTeams: "Teams",
      statTeamsSub: "registered",
      statPlayers: "Players",
      statPlayersSub: "rostered",
      statGroups: "Groups",
      statGroupsSub: "group stage",
      statStages: "Stages",
      statStagesSub: "groups → playoff",
      pillFormat: "Format",
      pillTeamsBy: "Teams by",
      formatLeague: "League",
      formatCup: "Cup",
      stageProgress: "{stage}"
    },
    community: {
      verdict: {
        eyebrow: "The bracket so far",
        story: "{team} are the story — the model had them {predicted}, they're sitting {place}.",
        letdown: "Meanwhile {team} are the bracket's let-down, slipping from a predicted {predicted} to {place}.",
        empty: "Too early to call — no team has strayed far from its forecast yet.",
        whatsThis: "What's this?"
      },
      kpi: {
        climbing: "Climbing",
        climbingFoot: "players ↑ a division",
        dropping: "Dropping",
        droppingFoot: "players ↓ a division",
        watch: "Watch flags",
        watchFoot: "need a human look",
        avgConfidence: "Avg confidence",
        avgConfidenceFoot: "across the bracket",
        upsets: "Upsets",
        upsetsFoot: "off forecast by 4+",
        newFaces: "New faces",
        newFacesFoot: "new player or role"
      },
      standings: {
        title: "Standings",
        rankedBy: "ranked by {algorithm}",
        sortStandings: "Standings",
        sortMovers: "Biggest movers",
        sortWatch: "Watch list",
        flagCount: "{count} flags",
        flagCountOne: "{count} flag",
        watchEmpty: "No watch flags right now — the bracket's clean.",
        group: "Grp {group}",
        onForm: "on form",
        predShort: "pred {place}",
        viewList: "List",
        viewTable: "Table"
      },
      horizon: {
        title: "Predicted vs Actual",
        allTeams: "all {count} teams",
        predicted: "Predicted",
        climbed: "Climbed",
        fellShort: "Fell short",
        scaleStart: "1st",
        scaleFinish: "finish →",
        scaleEnd: "{count}th",
        predictedTip: "Predicted {place}",
        finishedTip: "Finished {place}"
      },
      team: {
        rosterCount: "Roster · {count} players",
        predictedVsActual: "Predicted vs actual",
        predictedShort: "Predicted {place}",
        finishedShort: "Finished {place}",
        backTo: "Back to {team}",
        groupRecord: "Group {group} · {wins}–{losses}",
        pickPrompt: "Pick a team to dig into its roster."
      },
      player: {
        backTo: "Back to {team}",
        predictedMove: "Predicted move",
        climb: "Predicted to climb",
        drop: "Predicted to drop",
        hold: "Right where they belong",
        divMove: "Div {from} → Div {to}",
        impact: "Impact",
        confidence: "Confidence",
        impactElite: "elite for this tier",
        impactAbove: "above the median",
        impactMid: "around the median",
        impactBelow: "below the median",
        confidencePlenty: "plenty of data",
        confidenceSolid: "solid sample",
        confidenceThin: "thin sample",
        percentileTitle: "Impact percentile",
        percentileVs: "vs Div {division} {role}s",
        flagTitle: "{kind} flag",
        flagBody: "Automatically raised for review — not a verdict. Tap the ⓘ to see what \"{kind}\" means.",
        whyTitle: "Why the model says this",
        roleLine: "{role} · Div {division} · {team}",
        newTag: "new",
        newRoleTag: "new role"
      },
      move: {
        climb: "Climb",
        drop: "Drop",
        hold: "Hold"
      },
      why: {
        flag: "Flagged as {kind} — the model is holding its forecast until it sees more.",
        flagSignal: "Signal strength {pct}% · still under review.",
        climbImpact: "Top-tier impact among Div {division} {role}s this event.",
        climbConfidence: "The model is {pct}% confident — enough evidence to suggest a climb.",
        dropImpact: "Bottom-tier impact for a Div {division} {role}.",
        dropConsistent: "Consistent across {maps} maps, so the model leans toward a drop.",
        holdInBand: "Performing about where a Div {division} player should — no move expected.",
        holdThin: "Sample is still thin, so confidence is only {pct}%.",
        holdSteady: "Steady, in-band results across the bracket."
      },
      role: {
        tank: "Tank",
        damage: "Damage",
        support: "Support"
      }
    },
    howItWorks: {
      kicker: "How this works",
      title: "Reading the analytics",
      intro: "After every map, the model re-rates every player and team. This page turns that into three simple questions:",
      step1Title: "Who surprised us?",
      step1Body: "The verdict up top names the team that beat its predicted finish by the most — and the one that fell short.",
      step2Title: "Who's climbing or dropping?",
      step2Body: "Each player gets a predicted move — the model's read on whether they're playing above or below their current division.",
      step3Title: "How sure are we?",
      step3Body: "Confidence bars show how much data is behind each call. Tap any dotted term or the ⓘ to see what it means.",
      foot: "Nothing here is final — it's a live read that sharpens as the bracket plays out.",
      cardTitle: "New here? Read the analytics in 30s",
      cardSubtitle: "What every number on this page means."
    },
    sheet: {
      glossaryKicker: "Glossary",
      close: "Close",
      help: "How this works"
    }
  }
};
