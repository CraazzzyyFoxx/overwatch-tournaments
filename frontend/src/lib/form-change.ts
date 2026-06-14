export function hasUnsavedChanges<T>(currentValue: T, initialValue: T): boolean {
  return JSON.stringify(currentValue) !== JSON.stringify(initialValue);
}
