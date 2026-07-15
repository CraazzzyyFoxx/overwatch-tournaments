export type PublicPageQueryPresentation = {
  initialState: "skeleton" | "error" | null;
  contentState: "empty" | "content" | null;
  showUpdating: boolean;
  showRefreshError: boolean;
};

export type PublicPageQueryState = {
  data: unknown;
  itemCount: number;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
};

export function getPublicPageQueryPresentation({
  data,
  itemCount,
  isError,
  isFetching
}: PublicPageQueryState): PublicPageQueryPresentation {
  const hasCachedData = data !== undefined;

  return {
    initialState: hasCachedData ? null : isError ? "error" : "skeleton",
    contentState: hasCachedData ? (itemCount === 0 ? "empty" : "content") : null,
    showUpdating: hasCachedData && isFetching && !isError,
    showRefreshError: hasCachedData && isError
  };
}
