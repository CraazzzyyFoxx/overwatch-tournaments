import "@tanstack/react-query";

declare module "@tanstack/react-query" {
  interface Register {
    queryMeta: {
      /** Opt out of the global error toast for this query. */
      suppressErrorToast?: boolean;
    };
    mutationMeta: {
      /** Opt out of the global error toast for this mutation. */
      suppressErrorToast?: boolean;
    };
  }
}
