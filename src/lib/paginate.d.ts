export type PaginatedResponse<T> = {
  total?: number;
  [key: string]: unknown;
};

declare const paginate: {
  loadAllPages<T>(
    fetchPage: (params: { limit: number; offset: number }) => Promise<PaginatedResponse<T>>,
    collectionKey: string,
    pageSize: number,
    maxOffset?: number,
  ): Promise<T[]>;
};

export default paginate;
