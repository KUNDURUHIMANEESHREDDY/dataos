/**
 * Merge caller-provided request headers with DataOS JSON defaults.
 *
 * Using the Fetch Headers implementation makes this case-insensitive and
 * supports every HeadersInit form (Headers, tuples, and plain objects).
 */
export function mergeApiHeaders(input) {
  const headers = new Headers(input ?? undefined);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}
