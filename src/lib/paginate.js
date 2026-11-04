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


/**
 * Fetch a collection without allowing the browser graph to grow without bound.
 *
 * One extra record is requested at the cap so APIs that omit total can still
 * report truncation accurately. The extra record is never returned to callers.
 *
 * @template T
 * @param {(params: { limit: number; offset: number; signal?: AbortSignal }) => Promise<Record<string, unknown>>} fetchPage
 * @param {string} collectionKey
 * @param {number} pageSize
 * @param {number} maxItems
 * @param {AbortSignal} [signal]
 * @returns {Promise<{ items: T[]; total: number | null; truncated: boolean }>}
 */
async function loadBoundedPages(fetchPage, collectionKey, pageSize, maxItems, signal) {
  if (typeof fetchPage !== "function") {
    throw new TypeError("fetchPage must be a function");
  }
  if (typeof collectionKey !== "string" || collectionKey.length === 0) {
    throw new TypeError("collectionKey must be a non-empty string");
  }
  if (!Number.isSafeInteger(pageSize) || pageSize < 1) {
    throw new RangeError("pageSize must be a positive safe integer");
  }
  if (!Number.isSafeInteger(maxItems) || maxItems < 1) {
    throw new RangeError("maxItems must be a positive safe integer");
  }

  const items = [];
  let total = null;

  for (;;) {
    throwIfAborted(signal);
    const remaining = maxItems - items.length;
    // At the cap, make a one-record probe when the API omits total. This
    // distinguishes an exactly-full collection from a truncated one.
    const limit = Math.min(pageSize, remaining + 1);
    const offset = items.length;
    const page = await fetchPage({ limit, offset, signal });
    throwIfAborted(signal);

    if (!page || typeof page !== "object" || Array.isArray(page)) {
      throw new TypeError("Pagination response must be an object");
    }

    const batch = page[collectionKey];
    if (!Array.isArray(batch)) {
      throw new TypeError("Pagination response must contain an array named " + collectionKey);
    }
    if (batch.length > limit) {
      throw new RangeError("Pagination response exceeded the requested page size of " + limit);
    }

    if (page.total !== undefined && page.total !== null) {
      if (!Number.isSafeInteger(page.total) || page.total < 0) {
        throw new TypeError("Pagination total must be a non-negative safe integer");
      }
      total = page.total;
    }

    const accepted = batch.slice(0, remaining);
    items.push(...accepted);
    const loaded = offset + batch.length;

    if (total !== null && loaded >= total) {
      return { items, total, truncated: total > items.length };
    }

    if (batch.length < limit) {
      if (total !== null) {
        throw new Error(
          "Pagination returned a short page at offset " + offset
          + " before the reported total of " + total + " records",
        );
      }
      return { items, total: null, truncated: false };
    }

    if (items.length >= maxItems && total !== null) {
      return { items, total, truncated: total > items.length };
    }
    if (items.length >= maxItems && batch.length > accepted.length) {
      return { items, total, truncated: true };
    }
  }
}

module.exports = { loadAllPages, loadBoundedPages };
