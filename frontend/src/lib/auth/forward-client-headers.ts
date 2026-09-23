const HEADER_NAMES_TO_FORWARD = [
  "user-agent",
  "x-forwarded-for",
  "x-real-ip",
  "cf-connecting-ip",
  "true-client-ip",
  "x-client-ip",
  "x-vercel-forwarded-for",
] as const;

export function getForwardedClientHeaders(request: Request): Record<string, string> {
  const forwardedHeaders: Record<string, string> = {};

  for (const headerName of HEADER_NAMES_TO_FORWARD) {
    const value = request.headers.get(headerName);
    if (value) {
      forwardedHeaders[headerName] = value;
    }
  }

  const originalUserAgent = request.headers.get("user-agent");
  if (originalUserAgent) {
    forwardedHeaders["x-original-user-agent"] = originalUserAgent;
  }

  return forwardedHeaders;
}
