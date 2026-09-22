// Single logout path for every entry point (header menu, admin sidebar, account
// deletion). It POSTs — the route rejects GET on purpose, see the comment there —
// and then hands the browser a full navigation rather than a router push, so the
// whole client tree is rebuilt with no trace of the previous identity (stores,
// react-query cache, realtime socket).
export async function logout(target = "/"): Promise<void> {
  try {
    await fetch("/auth/logout", {
      method: "POST",
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" }
    });
  } catch {
    // Best effort. If the revoke never reached the server the session survives
    // server-side, but the navigation below must still happen: leaving the user
    // staring at a signed-in UI they just asked to leave is the worse failure.
  }
  window.location.assign(target);
}
