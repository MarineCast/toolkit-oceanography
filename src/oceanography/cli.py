"""python -m oceanography {collect,build,inspect,run}."""

import argparse
import os
import sys
from pathlib import Path
from importlib.resources import files

from .build import build
from .config import DEFAULT_CONFIG
from .download import FAMILIES, collect
from .inspect import inspect


def _run(args):
    options = dict(
        config=args.config, start=args.start, end=args.end, families=args.family or FAMILIES
    )
    if args.command in ("collect", "run"):
        collect(**options, offline=args.offline, refresh=args.refresh)
    if args.command in ("build", "run"):
        build(**options)
    if args.command == "compare" or (
        args.command == "run"
        and all(
            f in options["families"]
            for f in ["tides", "currents", "tidal_model", "offshore_currents", "productivity"]
        )
    ):
        from .compare import compare

        compare(config=args.config, start=args.start, end=args.end)
    if args.command in ("inspect", "run"):
        print(inspect(**options))


def initialize_workspace(root):
    """Copy packaged configuration without overwriting user files."""
    created = []
    def visit(source, relative):
        for item in sorted(source.iterdir(), key=lambda item: item.name):
            target = root / relative / item.name
            if item.is_dir():
                visit(item, relative / item.name)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(item.read_bytes())
                created.append(target)
    visit(files("oceanography").joinpath("resources/config"), Path("config"))
    return created


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'waves-salishseacast':
        from .waves_ssc import main as implementation
        return implementation(argv[1:])
    if argv and argv[0] == 'waves-usgs-nearshore':
        from .waves_usgs import main as implementation
        return implementation(argv[1:])
    if argv and argv[0] == 'waves':
        from .waves import main as waves_main
        return waves_main(argv[1:])
    if argv and argv[0] == 'liveocean-salinity-extension':
        from .liveocean_salinity import main as extension_main
        return extension_main(argv[1:])
    if argv and argv[0] == 'surface-history':
        from .surface_history import main as surface_main
        return surface_main(argv[1:])
    if argv and argv[0] == 'regional-filtered-pilot':
        from .regional_filtered import main as filtered_main
        return filtered_main(argv[1:])
    if argv and argv[0] == 'liveocean-history':
        from .liveocean import main as liveocean_main
        return liveocean_main(argv[1:])
    if argv and argv[0] == 'regional-history':
        from .regional_gap_history import main as regional_main
        return regional_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__, epilog='Monthly gap history: oceanography regional-history --help')
    parser.add_argument("command", choices=["init", "collect", "build", "inspect", "compare", "run"])
    parser.add_argument("--workspace", type=Path, help="Configuration and data root")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--family", action="append", choices=FAMILIES)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Collection may only use verified existing raw snapshots",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Recollect in a new immutable raw request directory, including updated metadata",
    )
    args = parser.parse_args(argv)
    if args.command != "init" and (not args.start or not args.end):
        parser.error("--start and --end are required for research commands")
    if args.offline and args.refresh:
        parser.error("--offline and --refresh cannot be combined")
    previous = os.environ.get("OCEANOGRAPHY_WORKSPACE")
    if args.workspace is not None:
        os.environ["OCEANOGRAPHY_WORKSPACE"] = str(args.workspace.expanduser().resolve())
    try:
        if args.command == "init":
            from .core.config.paths import project_root
            root = project_root()
            print(f"Initialized {root}: {len(initialize_workspace(root))} files created")
            return 0
        _run(args)
        return 0
    finally:
        if previous is None:
            os.environ.pop("OCEANOGRAPHY_WORKSPACE", None)
        else:
            os.environ["OCEANOGRAPHY_WORKSPACE"] = previous
