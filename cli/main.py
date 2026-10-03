"""
DataOS Command Line Interface (CLI) (Rule #33).
Interact with the Universal Data Operating System from the terminal.
"""

from __future__ import annotations
import sys
import argparse
import json
from dataos_system import DataOS


def _health(dataos: DataOS) -> dict:
    """Report real runtime state. DataOS exposes no health method, so this is
    assembled from the storage backend and the metrics system."""
    try:
        objects = dataos.storage.list_objects(limit=100000)
        object_count = len(objects)
    except Exception as exc:  # pragma: no cover - defensive
        object_count = f"unavailable: {exc}"

    report = {
        "db_path": dataos.db_path,
        "db_url": dataos.db_url,
        "storage_backend": type(dataos.storage).__name__,
        "object_count": object_count,
    }

    try:
        report["metrics"] = dataos.metrics.snapshot()
    except Exception as exc:  # pragma: no cover - defensive
        report["metrics"] = f"unavailable: {exc}"

    return report


def main():
    parser = argparse.ArgumentParser(description="DataOS — Universal Data Operating System CLI")
    subparsers = parser.add_subparsers(dest="command", help="DataOS commands")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a file into DataOS")
    ingest_parser.add_argument("file_path", help="Path to file to ingest")

    # SQL command
    sql_parser = subparsers.add_parser("sql", help="Execute SQL query against DataOS")
    sql_parser.add_argument("query", help="SQL query string")

    # Search command
    search_parser = subparsers.add_parser("search", help="Hybrid search across DataOS")
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results")

    # Health command
    subparsers.add_parser("health", help="Check DataOS health and catalog metrics")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export graph data")
    export_parser.add_argument("--format", choices=["json_ld", "graphml", "dot", "sql"], default="json_ld")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dataos = DataOS()

    try:
        if args.command == "ingest":
            res = dataos.ingest(args.file_path)
            print(json.dumps(res, indent=2, default=str))

        elif args.command == "sql":
            res = dataos.sql(args.query)
            print(json.dumps(res, indent=2, default=str))

        elif args.command == "search":
            res = dataos.search(args.query, top_k=args.limit)
            print(json.dumps(res, indent=2, default=str))

        elif args.command == "health":
            print(json.dumps(_health(dataos), indent=2, default=str))

        elif args.command == "export":
            if args.format == "json_ld":
                print(json.dumps(dataos.exporter.export_json_ld(), indent=2, default=str))
            elif args.format == "graphml":
                print(dataos.exporter.export_graphml())
            elif args.format == "dot":
                print(dataos.exporter.export_dot())
            elif args.format == "sql":
                print(dataos.exporter.export_sql_dump())
    finally:
        dataos.close()


if __name__ == "__main__":
    main()
