"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from eqm.config import get_settings
from eqm.engine import run_engine
from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    Violation,
)
from eqm.persistence import JsonStore
from eqm.rules.base import DataSnapshot
from eqm.scenarios import run_scenario
from eqm.seed import SeedBundle, SeedConfig, generate_seed
from eqm.simulator import drift_tick


def _bundle_from_store(store: JsonStore) -> SeedBundle:
    async def load():
        ents = [Entitlement(**x) for x in await store.read("entitlements.json")]
        emps = [HREmployee(**x) for x in await store.read("hr_employees.json")]
        ress = [CMDBResource(**x) for x in await store.read("cmdb_resources.json")]
        asns = [Assignment(**x) for x in await store.read("assignments.json")]
        return SeedBundle(entitlements=ents, hr_employees=emps,
                          cmdb_resources=ress, assignments=asns)
    return asyncio.run(load())


async def _save_bundle(store: JsonStore, b: SeedBundle, vios: list[Violation]) -> None:
    await store.write("entitlements.json", [e.model_dump(mode="json") for e in b.entitlements])
    await store.write("hr_employees.json", [e.model_dump(mode="json") for e in b.hr_employees])
    await store.write("cmdb_resources.json", [e.model_dump(mode="json") for e in b.cmdb_resources])
    await store.write("assignments.json", [e.model_dump(mode="json") for e in b.assignments])
    await store.write("violations.json", [v.model_dump(mode="json") for v in vios])


def _evaluate_and_save(store: JsonStore, b: SeedBundle) -> int:
    snap = DataSnapshot(b.entitlements, b.hr_employees, b.cmdb_resources, b.assignments)
    existing = [Violation(**x) for x in asyncio.run(store.read("violations.json"))]
    result = run_engine(snap, existing_violations=existing)
    asyncio.run(_save_bundle(store, b, result.violations))
    return result.new_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eqm")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--small", action="store_true", help="50/100/15/200 instead of full")
    sub.add_parser("drift")
    p_scen = sub.add_parser("scenario")
    p_scen.add_argument("name")
    sub.add_parser("evaluate")

    args = parser.parse_args(argv)
    settings = get_settings()
    store = JsonStore(settings.data_dir)

    if args.cmd == "seed":
        cfg = (SeedConfig(num_entitlements=50, num_employees=100,
                          num_resources=15, num_assignments=200, seed=42)
               if args.small else SeedConfig())
        bundle = generate_seed(cfg)
        new_count = _evaluate_and_save(store, bundle)
        print(f"seeded; new violations={new_count}")
        return 0

    if args.cmd == "drift":
        bundle = _bundle_from_store(store)
        tick = int(datetime.now().timestamp()) // 60
        summary = drift_tick(bundle, tick_number=tick)
        new_count = _evaluate_and_save(store, bundle)
        print(f"drift tick={tick} changes={len(summary.changes)} new_violations={new_count}")
        return 0

    if args.cmd == "scenario":
        bundle = _bundle_from_store(store)
        run_scenario(args.name, bundle)
        new_count = _evaluate_and_save(store, bundle)
        print(f"scenario={args.name} new_violations={new_count}")
        return 0

    if args.cmd == "evaluate":
        bundle = _bundle_from_store(store)
        new_count = _evaluate_and_save(store, bundle)
        print(f"evaluated; new_violations={new_count}")
        return 0

    parser.error("no command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
