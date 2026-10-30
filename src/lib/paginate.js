/**
 * Fetch a complete collection from an offset-paginated API.
 *
 * The backend's maximum offset is enforced locally so a large collection fails
 * with an actionable error instead of issuing a request the API will reject.
 *
 * @template T
 * @param {(params: { limit: number; offset: number }) => Promise<Record<string, unknown>>} fetchPage
 * @param {string} collectionKey
 * @param {number} pageSize
 * @param {number} [maxOffset=1000000]
 * @returns {Promise<T[]>}
 */
export async function loadAllPages(fetchPage, collectionKey, pageSize, maxOffset = 1_000_000) {
  if (typeof fetchPage !== "function") {
    throw new TypeError("fetchPage must be a function");
  }
  if (typeof collectionKey !== "string" || collectionKey.length === 0) {
    throw new TypeError("collectionKey must be a non-empty string");
  }
  if (!Number.isSafeInteger(pageSize) || pageSize < 1) {
    throw new RangeError("pageSize must be a positive safe integer");
  }
  if (!Number.isSafeInteger(maxOffset) || maxOffset < 0) {
    throw new RangeError("maxOffset must be a non-negative safe integer");
  }

  const results = [];
  for (let offset = 0; ; offset += pageSize) {
    if (offset > maxOffset) {
      throw new Error(`Pagination exceeded the API offset limit of ${maxOffset}`);
    }

    const page = await fetchPage({ limit: pageSize, offset });
    const items = Array.isArray(page?.[collectionKey]) ? page[collectionKey] : [];
    results.push(...items);

    const total = Number.isSafeInteger(page?.total) && page.total >= 0
      ? page.total
      : null;
    if (items.length < pageSize || (total !== null && offset + items.length >= total)) {
      return results;
    }

    if (offset + pageSize > maxOffset) {
      throw new Error(
        `Pagination reached the API offset limit of ${maxOffset} before loading all ${total ?? "available"} records`,
      );
    }
  }
}
