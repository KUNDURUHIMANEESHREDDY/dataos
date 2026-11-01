/**
 * Fetch a complete collection from an offset-paginated API.
 *
 * The backend's maximum offset is enforced locally so a large collection fails
 * with an actionable error instead of issuing a request the API will reject.
 *
 * @template T
 * @param {(params: { limit: number; offset: number; signal?: AbortSignal }) => Promise<Record<string, unknown>>} fetchPage
 * @param {string} collectionKey
 * @param {number} pageSize
 * @param {number} [maxOffset=1000000]
 * @param {AbortSignal} [signal]
 * @returns {Promise<T[]>}
 */
function throwIfAborted(signal) {
  if (!signal?.aborted) return;
  if (signal.reason instanceof Error) throw signal.reason;
  const error = new Error("Pagination was aborted");
  error.name = "AbortError";
  throw error;
}

async function loadAllPages(fetchPage, collectionKey, pageSize, maxOffset = 1_000_000, signal) {
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
    throwIfAborted(signal);
    if (offset > maxOffset) {
      throw new Error("Pagination exceeded the API offset limit of " + maxOffset);
    }

    const page = await fetchPage({ limit: pageSize, offset, signal });
    throwIfAborted(signal);
    if (!page || typeof page !== "object" || Array.isArray(page)) {
      throw new TypeError("Pagination response must be an object");
    }
    const items = page[collectionKey];
    if (!Array.isArray(items)) {
      throw new TypeError("Pagination response must contain an array named " + collectionKey);
    }
    if (items.length > pageSize) {
      throw new RangeError("Pagination response exceeded the requested page size of " + pageSize);
    }
    results.push(...items);

    const total = page.total === undefined || page.total === null
      ? null
      : page.total;
    if (total !== null && (!Number.isSafeInteger(total) || total < 0)) {
      throw new TypeError("Pagination total must be a non-negative safe integer");
    }

    if (total !== null) {
      const loaded = offset + items.length;
      if (loaded >= total) {
        return results;
      }
      if (items.length < pageSize) {
        throw new Error(
          "Pagination returned a short page at offset " + offset
          + " before the reported total of " + total + " records",
        );
      }
    } else if (items.length < pageSize) {
      return results;
    }

    if (offset + pageSize > maxOffset) {
      throw new Error(
        "Pagination reached the API offset limit of " + maxOffset
        + " before loading all " + (total ?? "available") + " records",
      );
    }
  }
}

module.exports = { loadAllPages };
