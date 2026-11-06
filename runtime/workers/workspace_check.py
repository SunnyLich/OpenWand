"""Fixed, read-only syntax/data checks for the frozen app's module entry point.

Compile source in memory without executing it or creating bytecode files.
Workspace path/type/size validation is performed by LimitedWorkspaceRunner.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("python_syntax", "json"))
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        for path in args.paths:
            if args.check == "python_syntax":
                compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
            else:
                with path.open(encoding="utf-8") as source:
                    json.load(source)
    except (SyntaxError, ValueError, OSError) as error:
        # A controlled nonzero exit avoids a windowed bootloader error dialog.
        if sys.stderr is not None:
            print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
