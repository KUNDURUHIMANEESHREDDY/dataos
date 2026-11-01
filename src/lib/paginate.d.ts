export type PaginatedResponse<T> = {
  total?: number;
  [key: string]: unknown;
};

declare const paginate: {
  loadAllPages<T>(
    fetchPage: (params: { limit: number; offset: number; signal?: AbortSignal }) => Promise<PaginatedResponse<T>>,
    collectionKey: string,
    pageSize: number,
    maxOffset?: number,
    signal?: AbortSignal,
  ): Promise<T[]>;
};

export default paginate;
