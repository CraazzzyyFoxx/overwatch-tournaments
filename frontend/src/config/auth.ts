export const AUTH_REQUIRED_ROUTE_PREFIXES = ["/admin", "/balancer"] as const;

export function isAuthRequiredPath(pathname: string): boolean {
  return AUTH_REQUIRED_ROUTE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
