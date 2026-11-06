export type IngestionFile = {
  filename: string;
  read: () => Promise<string>;
};

export type IngestionOutcome =
  | {
      filename: string;
      ok: true;
      objectsCreated: number;
      relationsCreated: number;
    }
  | {
      filename: string;
      ok: false;
      error: string;
    };

function readCount(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

/**
 * Ingest files one at a time so large browser uploads do not multiply memory
 * usage. A failed read or request is isolated to that file; later files still
 * run and the caller can report partial success.
 */
export async function ingestFiles(
  files: readonly IngestionFile[],
  fetcher: typeof fetch = fetch,
): Promise<IngestionOutcome[]> {
  const outcomes: IngestionOutcome[] = [];

  for (const file of files) {
    let content: string;
    try {
      content = await file.read();
    } catch {
      outcomes.push({ filename: file.filename, ok: false, error: "unable to read file" });
      continue;
    }

    let response: Response;
    try {
      response = await fetcher("/api/ingest/universal", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          filename: file.filename,
          content,
          discover_relations: "true",
        }),
      });
    } catch {
      outcomes.push({ filename: file.filename, ok: false, error: "request failed" });
      continue;
    }

    if (!response.ok) {
      if (response.body) {
        try {
          await response.body.cancel();
        } catch {
          // The response may already have been closed by the transport.
        }
      }
      outcomes.push({ filename: file.filename, ok: false, error: `HTTP ${response.status}` });
      continue;
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      outcomes.push({ filename: file.filename, ok: false, error: "invalid ingestion response" });
      continue;
    }

    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      outcomes.push({ filename: file.filename, ok: false, error: "invalid ingestion response" });
      continue;
    }

    const data = payload as Record<string, unknown>;
    outcomes.push({
      filename: file.filename,
      ok: true,
      objectsCreated: readCount(data.objects_created),
      relationsCreated: readCount(data.relations_created),
    });
  }

  return outcomes;
}
