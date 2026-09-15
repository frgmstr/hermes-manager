#!/usr/bin/env python3
"""
Replace model name variants in Python scripts.

Auto-orders old-model variants by string length (longest first to avoid
partial-match corruption), removes duplicate adjacent entries in list literals,
and runs py_compile to verify syntax.

Usage:
    python replace_model_in_py.py \
      --old microsoft/phi-4-mini-reasoning,phi-4-mini-reasoning,phi-4-mini,phi-4 \
      --new ornith-1.5-9b \
      profiles/archality-social-media/scripts/morning_brief.py

    # Dry run:
    python replace_model_in_py.py --old a,b,c --new new-model file.py --dry-run
"""

import argparse
import py_compile
import re
import sys
from pathlib import Path


def dedupe_adjacent(content: str, model_name: str) -> tuple[str, int]:
    """Remove duplicate adjacent entries of model_name in list literals.

    Handles multi-line and same-line adjacent duplicates.
    """
    escaped = re.escape(model_name)
    pattern = re.compile(rf'"{escaped}",\s+"{escaped}"\s*,?')
    return pattern.subn(rf'"{model_name}",', content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace model name variants in Python scripts."
    )
    parser.add_argument(
        "--old", required=True,
        help="Comma-separated old model name variants",
    )
    parser.add_argument(
        "--new", required=True,
        help="New model name",
    )
    parser.add_argument("files", nargs="+", help="Python files to update")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    old_variants = [v.strip() for v in args.old.split(",") if v.strip()]
    # Sort longest-first so short prefixes don't corrupt long matches
    old_variants.sort(key=len, reverse=True)

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"  WARNING: {filepath}: not found", file=sys.stderr)
            continue

        original = path.read_text(encoding="utf-8")
        content = original

        for variant in old_variants:
            count = content.count(variant)
            if count:
                content = content.replace(variant, args.new)
                print(f"  '{variant}' -> '{args.new}' ({count} match(es))")

        content, dup_count = dedupe_adjacent(content, args.new)
        if dup_count:
            print(f"  Removed {dup_count} duplicate(s) of '{args.new}' in list literals")

        if args.dry_run:
            print(f"  [dry-run] {filepath}")
            continue

        if content != original:
            path.write_text(content, encoding="utf-8")
            print(f"  OK: {filepath} - updated")
        else:
            print(f"  - {filepath} - no changes needed")

        try:
            py_compile.compile(str(path), doraise=True)
            print(f"  OK: syntax valid")
        except py_compile.PyCompileError as e:
            print(f"  ERROR: SYNTAX ERROR: {e}", file=sys.stderr)
            if not args.dry_run:
                print("  FIX THE FILE - py_compile failed!", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
