"""Generate the browsable API reference from Wisp's own docstrings.

The output is derived from the source, so it is gitignored and safe to delete;
re-run this script to rebuild it.

Every module is passed to pdoc explicitly rather than letting pdoc walk the
packages. Package recursion honours ``__all__``, and four of Wisp's packages
declare one (``core/harness_clients``, ``core/context_router``,
``core/conversation_store``, ``runtime/brain/wisp_brain``). Relying on
recursion silently drops their submodules -- ``codex.py`` and the brain
``handlers.py`` among them -- which produces a reference that looks complete
and is not.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "api"

# Package roots documented under their own dotted path.
PACKAGE_ROOTS = ("core", "runtime", "ui", "addons")

# Single-file modules at the repo root worth documenting.
ROOT_MODULES = ("config",)

# Directories imported as top-level packages after their parent joins sys.path,
# mirroring how the app and tests/integration/brain/conftest.py import them.
SYS_PATH_PACKAGES = ((Path("runtime") / "brain", "wisp_brain"),)

SKIP_DIR_NAMES = {"__pycache__", "tests", "test"}


def _module_names(root: Path, base: Path, exclude: tuple[Path, ...] = ()) -> list[str]:
    """Return dotted names for every .py file under ``root``."""
    names: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(base).parts):
            continue
        if any(path.is_relative_to(directory) for directory in exclude):
            continue
        relative = path.relative_to(base).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        names.append(".".join(parts))
    return names


def discover_modules() -> list[str]:
    """List every importable app module, submodules included."""
    modules: list[str] = []
    # These live inside a package root but are imported as top-level packages,
    # so the walk below must not also claim them under their nested path.
    nested = tuple(REPO_ROOT / relative for relative, _ in SYS_PATH_PACKAGES)
    for name in PACKAGE_ROOTS:
        root = REPO_ROOT / name
        if root.is_dir():
            modules.extend(_module_names(root, REPO_ROOT, exclude=nested))
    for name in ROOT_MODULES:
        if (REPO_ROOT / f"{name}.py").is_file():
            modules.append(name)
    for relative, package in SYS_PATH_PACKAGES:
        root = REPO_ROOT / relative / package
        if root.is_dir():
            modules.extend(_module_names(root, REPO_ROOT / relative))
    return sorted(dict.fromkeys(modules))


def _environment() -> dict[str, str]:
    """Build a subprocess environment that keeps doc generation headless."""
    env = dict(os.environ)
    # Importing ui modules constructs Qt types; never surface a real window.
    env["QT_QPA_PLATFORM"] = "offscreen"
    extra = [str(REPO_ROOT), *(str(REPO_ROOT / relative) for relative, _ in SYS_PATH_PACKAGES)]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*extra, existing]) if existing else os.pathsep.join(extra)
    return env


def build(output: Path, *, show_source: bool) -> int:
    """Render the API reference, returning pdoc's exit status."""
    if importlib.util.find_spec("pdoc") is None:
        print(
            "pdoc is not installed in this interpreter.\n"
            f"  {Path(sys.executable).name} -m pip install pdoc",
            file=sys.stderr,
        )
        return 1
    modules = discover_modules()
    if not modules:
        print("no modules discovered; run this from the repo checkout", file=sys.stderr)
        return 1
    command = [
        sys.executable,
        "-m",
        "pdoc",
        "--output-directory",
        str(output),
        "--docformat",
        "google",
        "--no-search" if len(modules) < 2 else "--search",
    ]
    if not show_source:
        command.append("--no-show-source")
    command.extend(modules)
    print(f"documenting {len(modules)} modules -> {output}")
    return subprocess.run(command, cwd=REPO_ROOT, env=_environment(), check=False).returncode


def main() -> int:
    """Parse arguments and build the reference."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"directory to write HTML into (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--no-source",
        action="store_true",
        help="omit embedded source code, which is most of the output size",
    )
    parser.add_argument("--open", action="store_true", help="open the result in a browser")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the discovered module list and exit without building",
    )
    args = parser.parse_args()

    if args.list:
        for name in discover_modules():
            print(name)
        return 0

    status = build(args.output, show_source=not args.no_source)
    if status == 0 and args.open:
        webbrowser.open((args.output / "index.html").resolve().as_uri())
    return status


if __name__ == "__main__":
    raise SystemExit(main())
