export const AUTH_UNAUTHORIZED_EVENT = "auth:unauthorized";

export function notifyUnauthorized() {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
}
