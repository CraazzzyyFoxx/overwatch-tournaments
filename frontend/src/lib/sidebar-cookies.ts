export const SIDEBAR_COOKIE_MAX_AGE = 60 * 60 * 24 * 7;

export const SIDEBAR_COOKIE_NAMES = {
  default: "sidebar_state",
  admin: "admin_sidebar_state",
  balancer: "balancer_sidebar_state",
} as const;

export function parseSidebarOpenCookie(value: string | undefined): boolean | undefined {
  if (value === "true") {
    return true;
  }

  if (value === "false") {
    return false;
  }

  return undefined;
}
