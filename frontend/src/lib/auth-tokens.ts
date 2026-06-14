let refreshInFlight: Promise<string | undefined> | null = null;

export async function getTokenFromCookies(cookieName: string): Promise<string | undefined> {
  if (typeof window === "undefined") {
    try {
      const { cookies } = await import("next/headers");
      const cookieStore = await cookies();
      return cookieStore.get(cookieName)?.value;
    } catch {
      return undefined;
    }
  }

  try {
    const Cookies = (await import("js-cookie")).default;
    return Cookies.get(cookieName);
  } catch {
    return undefined;
  }
}

export async function setTokenInCookies(cookieName: string, value: string): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const Cookies = (await import("js-cookie")).default;
    Cookies.set(cookieName, value);
  } catch {
    // ignore
  }
}

export async function refreshAccessToken(): Promise<string | undefined> {
  // In SSR we rely on middleware to keep tokens fresh.
  if (typeof window === "undefined") return undefined;

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch("/auth/refresh", {
          method: "POST",
          cache: "no-store",
          credentials: "include",
          headers: {
            Accept: "application/json"
          },
        });

        if (!res.ok) return undefined;

        const tokens = (await res.json()) as { access_token?: string };
        if (tokens.access_token) {
          await setTokenInCookies("aqt_access_token", tokens.access_token);
        }
        return tokens.access_token;
      } catch {
        return undefined;
      } finally {
        refreshInFlight = null;
      }
    })();
  }

  return refreshInFlight;
}
