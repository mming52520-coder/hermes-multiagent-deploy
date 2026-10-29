#!/usr/bin/env python3
"""Read-only provenance checks for the one supported Hermes source baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

COMMIT = "aaf5691261f12601db845386d650dce1cdfa30f9"
VERSION = "0.18.2"
ARCHIVE_SHA256 = "34f9eedb7215eb9768b6f8289d0284e01fa467c86228ac7e5b6054fc8698e628"
INSTALLER_SHA256 = "c2e4326c1660bd45f64321996eb15bda35e7a4649e32a310495a61972a2804c8"


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def verify_source(source: Path, archive: Path | None = None) -> dict:
    source = source.resolve()
    if (source / ".git").exists():
        root = Path(git(source, "rev-parse", "--show-toplevel")).resolve()
        if root != source or git(source, "rev-parse", "HEAD") != COMMIT:
            raise ValueError("unsupported Hermes source commit")
        if git(source, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("Hermes source contains tracked modifications")
        method = "git"
    elif archive is not None:
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Hermes source archive checksum mismatch")
        # A version string or marker alone does not prove the installed source.
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if not member.isfile():
                    continue
                relative = Path(member.name).relative_to(f"hermes-agent-{COMMIT}")
                actual = source / relative
                if not actual.is_file() or not actual.resolve().is_relative_to(source):
                    raise ValueError(f"missing or escaped baseline file: {relative}")
                expected_stream = bundle.extractfile(member)
                with actual.open("rb") as stream:
                    actual_hash = hashlib.file_digest(stream, "sha256").digest()
                if hashlib.file_digest(expected_stream, "sha256").digest() != actual_hash:
                    raise ValueError(f"modified baseline file: {relative}")
        method = "verified-archive"
    else:
        raise ValueError("source commit cannot be established; provide a verified baseline archive")
    import tomllib
    declared = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    if declared["project"]["version"] != VERSION:
        raise ValueError("unsupported Hermes package version")
    return {"version": VERSION, "commit": COMMIT, "source": str(source), "method": method}


def installed_source(hermes_bin: str) -> Path:
    output = subprocess.check_output([hermes_bin, "--version"], text=True)
    if f"Hermes Agent v{VERSION} " not in output and f"Hermes Agent v{VERSION}\n" not in output:
        raise ValueError("unsupported Hermes CLI version")
    directories = [line.removeprefix("Install directory: ") for line in output.splitlines()
                   if line.startswith("Install directory: ")]
    if len(directories) != 1:
        raise ValueError("CLI did not identify its actual install directory")
    return Path(directories[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-bin", default="hermes")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        source = args.source or installed_source(args.hermes_bin)
        print(json.dumps(verify_source(source, args.archive), ensure_ascii=False))
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, f"BASELINE REJECTED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
