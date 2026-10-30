export type PaginatedResponse<T> = {
  total?: number;
  [key: string]: unknown;
};

export function loadAllPages<T>(
  fetchPage: (params: { limit: number; offset: number }) => Promise<PaginatedResponse<T>>,
  collectionKey: string,
  pageSize: number,
  maxOffset?: number,
): Promise<T[]>;
