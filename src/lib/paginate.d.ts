export type PaginatedResponse<T> = {
  total?: number;
  [key: string]: unknown;
};

export type BoundedPageResult<T> = {
  items: T[];
  total: number | null;
  truncated: boolean;
};

declare const paginate: {
  loadAllPages<T>(
    fetchPage: (params: { limit: number; offset: number }) => Promise<PaginatedResponse<T>>,
    collectionKey: string,
    pageSize: number,
    maxOffset?: number,
  ): Promise<T[]>;
  loadBoundedPages<T>(
    fetchPage: (params: { limit: number; offset: number }) => Promise<PaginatedResponse<T>>,
    collectionKey: string,
    pageSize: number,
    maxItems: number,
  ): Promise<BoundedPageResult<T>>;
};

export default paginate;
