interface DraftLoadingQueryState<T> {
  data: T | null | undefined;
  isPending: boolean;
  isFetching: boolean;
}

export function shouldShowInitialDraftSkeleton<T>({
  data,
  isPending,
  isFetching
}: DraftLoadingQueryState<T>): boolean {
  return data == null && isPending && isFetching;
}
