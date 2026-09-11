const AUTH_REQUIRED_ROUTE_PREFIXES = ["/admin", "/balancer"] as const;

// Mix boards are the one public corner of the tool: the gateway serves their
// reads without identity, and a host reads them out to players who have no
// account here. Without this exception a 401 from any other request bounces a
// signed-out visitor off the page and pops the sign-in modal.
const PUBLIC_ROUTE_PREFIXES = ["/balancer/mix"] as const;

export function isAuthRequiredPath(pathname: string): boolean {
  if (PUBLIC_ROUTE_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return false;
  }
  return AUTH_REQUIRED_ROUTE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
