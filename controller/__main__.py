import argparse
import json
import logging
from pathlib import Path

from .api import SimulatorAPI
from .locking import exclusive_writer
from .runner import run
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Durable workflow controller (observe-only milestone)")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("run", help="Ingest and advance the simulator; no config changes yet")
    start.add_argument("--url", required=True)
    start.add_argument("--db", default="state/controller.sqlite3")
    start.add_argument("--max-ticks", type=int, help="Pause after this many advances; restart to resume")
    status = commands.add_parser("status", help="Read consolidated KPIs from our database")
    status.add_argument("--db", default="state/controller.sqlite3")
    explain = commands.add_parser("explain", help="Show observed changes and config history")
    explain.add_argument("workflow_id")
    explain.add_argument("--db", default="state/controller.sqlite3")
    explain.add_argument("--at", help="Changes through this ISO timestamp, including timezone")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "run":
        with exclusive_writer(args.db):
            store = Store(args.db)
            api = SimulatorAPI(args.url)
            try:
                result = run(api, store, max_ticks=args.max_ticks)
            finally:
                api.close()
                store.close()
    else:
        if not Path(args.db).is_file():
            parser.error(f"Database does not exist: {args.db}")
        store = Store(args.db, read_only=True)
        try:
            result = store.status() if args.command == "status" else store.explain(args.workflow_id, args.at)
        finally:
            store.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
