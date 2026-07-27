export interface Page<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export function normalizePage<T>(value: T[] | Page<T>): Page<T> {
  return Array.isArray(value)
    ? { next: null, previous: null, results: value }
    : value;
}
