"""
DataOS Command Line Interface (CLI) (Rule #33).
Interact with the Universal Data Operating System from the terminal.
"""

from __future__ import annotations
import sys
import argparse
import json
from dataos_system import DataOS


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

    if args.command == "ingest":
        res = dataos.ingest_file(args.file_path)
        print(json.dumps(res, indent=2))

    elif args.command == "sql":
        res = dataos.execute_sql(args.query)
        print(json.dumps(res, indent=2))

    elif args.command == "search":
        res = dataos.search.search(args.query, limit=args.limit)
        print(json.dumps(res, indent=2))

    elif args.command == "health":
        res = dataos.get_system_health()
        print(json.dumps(res, indent=2))

    elif args.command == "export":
        if args.format == "json_ld":
            print(json.dumps(dataos.exporter.export_json_ld(), indent=2))
        elif args.format == "graphml":
            print(dataos.exporter.export_graphml())
        elif args.format == "dot":
            print(dataos.exporter.export_dot())
        elif args.format == "sql":
            print(dataos.exporter.export_sql_dump())


if __name__ == "__main__":
    main()
