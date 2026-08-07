#!/usr/bin/env python3
"""Single content_hash algorithm for doctor + reconcile (stdlib only).

Matches official-style SSOT folder hash:
  non-hidden files, relative paths sorted, for each file: path\\0content\\0 → SHA-256 hex.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def dir_hash(root: Path) -> str | None:
    """Return hex digest of skill directory, or None if unreadable / not a dir."""
    if not root.is_dir():
        return None
    files: list[Path] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".")]
        for fn in fns:
            if fn.startswith("."):
                continue
            files.append(Path(dp) / fn)
    files.sort()
    h = hashlib.sha256()
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        try:
            h.update(fp.read_bytes())
            h.update(b"\0")
        except OSError:
            return None
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: content_hash.py <skill-directory>", file=sys.stderr)
        return 2
    got = dir_hash(Path(args[0]).resolve())
    if got is None:
        print("error: not a readable directory", file=sys.stderr)
        return 1
    print(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
