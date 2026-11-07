import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import app as api


def run(coro):
    return asyncio.run(coro)


def test_universal_ingestion_rejects_content_over_five_mib(monkeypatch):
    called = []

    def ingest(*args, **kwargs):
        called.append((args, kwargs))
        return {"status": "ingested"}

    monkeypatch.setattr(api, "dataos", SimpleNamespace(ingest=ingest))
    content = chr(0xE9) * (api.MAX_INGEST_CONTENT_BYTES // 2 + 1)

    with pytest.raises(HTTPException) as exc:
        run(api.universal_ingest_api(filename="large.txt", content=content, current_user=None))

    assert exc.value.status_code == 413
    assert exc.value.detail == "Ingestion file exceeds the 5 MiB content limit."
    assert called == []


def test_universal_ingestion_accepts_content_at_five_mib(monkeypatch):
    calls = []

    def ingest(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "ingested"}

    monkeypatch.setattr(api, "dataos", SimpleNamespace(ingest=ingest))
    content = "a" * api.MAX_INGEST_CONTENT_BYTES

    result = run(api.universal_ingest_api(filename="limit.txt", content=content, current_user=None))

    assert result == {"status": "ingested"}
    assert len(calls) == 1
    assert calls[0][0][0] == content
