export interface Page<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export class CollectionContractError extends Error {
  constructor() {
    super("Collection response is not a supported paginated result");
    this.name = "CollectionContractError";
  }
}

export function normalizePage<T>(value: unknown): Page<T> {
  if (Array.isArray(value)) {
    return { next: null, previous: null, results: value as T[] };
  }
  if (
    typeof value !== "object" ||
    value === null ||
    !("next" in value) ||
    !("previous" in value) ||
    !("results" in value) ||
    (value.next !== null && typeof value.next !== "string") ||
    (value.previous !== null && typeof value.previous !== "string") ||
    !Array.isArray(value.results)
  ) {
    throw new CollectionContractError();
  }
  return value as Page<T>;
}

export function cursorFromPageLink(
  link: unknown,
  currentCursor: string | null,
): string | null {
  if (typeof link !== "string" || link.length === 0) return null;
  try {
    const cursor = new URL(link, window.location.origin).searchParams.get(
      "cursor",
    );
    return cursor && cursor !== currentCursor ? cursor : null;
  } catch {
    return null;
  }
}
