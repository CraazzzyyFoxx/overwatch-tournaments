type LocationSnapshot = {
  pathname?: string;
  search?: string;
  hash?: string;
};

export function getCurrentPathForAuthRedirect(location: LocationSnapshot | undefined): string {
  const pathname =
    location?.pathname && location.pathname.startsWith("/") ? location.pathname : "/";

  return `${pathname}${location?.search ?? ""}${location?.hash ?? ""}`;
}
