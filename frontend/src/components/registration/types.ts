export type AdditionalRole = {
  code: string;
  subrole: string;
  /** Ordered hero slugs (top picks) for this additional role. */
  topHeroes: string[];
};

export interface WizardState {
  step: number;
  values: Record<string, string>;
  smurfTags: string[];
  isFlex: boolean;
  primaryRole: string;
  subrole: string;
  /** Ordered hero slugs (top picks) for the primary role. */
  primaryRoleHeroes: string[];
  /** Ordered hero slugs (top picks) for a flex registration (any class). */
  flexHeroes: string[];
  additionalRoles: AdditionalRole[];
}

export type WizardAction =
  | { type: "SET_STEP"; step: number }
  | { type: "SET_VALUE"; key: string; value: string }
  | { type: "SET_SMURF_TAGS"; tags: string[] }
  | { type: "SET_FLEX"; isFlex: boolean }
  | { type: "SET_PRIMARY_ROLE"; role: string }
  | { type: "SET_SUBROLE"; subrole: string }
  | { type: "SET_ADDITIONAL_ROLES"; roles: AdditionalRole[] }
  | { type: "SET_PRIMARY_ROLE_HEROES"; heroes: string[] }
  | { type: "SET_FLEX_HEROES"; heroes: string[] }
  | { type: "INIT_VALUES"; values: Record<string, string> };
