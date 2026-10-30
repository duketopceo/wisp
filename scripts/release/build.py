#!/usr/bin/env python3
"""Build deterministic Linux release payloads using only the standard library."""
import argparse
import gzip
import hashlib
import io
import json
import pathlib
import re
import stat
import struct
import tarfile

TARGETS = {"linux-x86_64": 62, "linux-aarch64": 183}
# Runtime/resource trees, not the repository root. Never copy build tool trees.
TREES = ("wisp", "shells", "shell-plugin", "assets", "docs", "browser-extension")
FILES = ("wispd", "LICENSE", "README.md", "CHANGELOG.md",
         "THIRD_PARTY_NOTICES.md", "pyproject.toml",
         "scripts/build_harness.py", "scripts/fetch_whisper.sh")
SCRIPT_TREES = ("scripts/units", "scripts/cua", "scripts/bootstrap")
SKIP = {".git", ".env", ".venv", "venv", "node_modules", "build", "dist",
        "target", "__pycache__", ".cache", "cache", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".DS_Store"}


def excluded(path):
    return any(p in SKIP or p.startswith(".env.") for p in path.parts) \
        or path.suffix in {".pyc", ".pyo"}


def collect(source, names=(*TREES, *SCRIPT_TREES, *FILES)):
    """Dereference in-tree debug-shell links, reject external or cyclic links."""
    source = pathlib.Path(source).resolve(strict=True)
    files = {}

    def visit(path, relative, ancestors=()):
        if excluded(relative):
            return
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(source):
            raise ValueError(f"resource escapes source: {relative}")
        if resolved in ancestors:
            raise ValueError(f"cyclic resource link: {relative}")
        if resolved.is_dir():
            for child in sorted(resolved.iterdir()):
                visit(child, relative / child.name, (*ancestors, resolved))
        elif resolved.is_file():
            mode = 0o755 if resolved.stat().st_mode & 0o111 else 0o644
            files[relative.as_posix()] = (resolved.read_bytes(), mode)
        else:
            raise ValueError(f"not a regular resource: {relative}")

    for name in names:
        visit(source / name, pathlib.Path(name))
    return files


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def archive_files(files, archive, prefix, epoch):
    """Fixed order, gzip header, owner, mode and timestamp; no links in tar."""
    with archive.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                           compresslevel=9, mtime=epoch) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tf:
                for name, (data, mode) in sorted(files.items()):
                    info = tarfile.TarInfo(f"{prefix}/{name}")
                    info.size, info.mode, info.mtime = len(data), mode, epoch
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tf.addfile(info, io.BytesIO(data))


def bundle(args):
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", args.version):
        raise ValueError("version must be a vMAJOR.MINOR.PATCH release tag")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("commit must be a full lowercase 40-hex source SHA")
    if not 0 <= args.epoch <= 0xFFFFFFFF:
        raise ValueError("epoch must fit the gzip timestamp")
    source, out = pathlib.Path(args.source).resolve(), pathlib.Path(args.out).resolve()
    if out == source or any(out.is_relative_to(source / tree)
                            for tree in (*TREES, *SCRIPT_TREES)):
        raise ValueError("output must not be inside a packaged source tree")
    binary = pathlib.Path(args.binary)
    if binary.is_symlink() or not stat.S_ISREG(binary.stat().st_mode):
        raise ValueError("binary must be a regular file, not a symlink")
    data = binary.read_bytes()
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01" \
            or struct.unpack_from("<H", data, 18)[0] != TARGETS[args.target]:
        raise ValueError(f"binary must be a 64-bit little-endian ELF for {args.target}")
    files = collect(args.source)
    files["bin/wispd-rs"] = (data, 0o755)
    manifest = json.loads(files["shell-plugin/manifest.json"][0])
    manifest["version"] = args.version[1:]
    files["shell-plugin/manifest.json"] = (encoded(manifest), 0o644)
    metadata = {"schema": 1, "version": args.version, "commit": args.commit,
                "target": args.target, "source_date_epoch": args.epoch}
    files["release.json"] = (encoded(metadata), 0o644)
    inventory = {name: {"sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content), "mode": mode}
                 for name, (content, mode) in sorted(files.items())}
    files["payload.json"] = (encoded({"schema": 1, "files": inventory}), 0o644)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"wisp-{args.target}.tar.gz"
    archive_files(files, archive, f"wisp-{args.target}", args.epoch)
    print(archive)


def checksums(args):
    paths = [pathlib.Path(p) for p in args.assets]
    if len({p.name for p in paths}) != len(paths):
        raise ValueError("checksum asset basenames must be unique")
    rows = []
    for path in sorted(paths, key=lambda p: p.name):
        if not re.fullmatch(r"wisp-[A-Za-z0-9._-]+\.tar\.gz", path.name):
            raise ValueError(f"unexpected release asset name: {path.name}")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"asset must be a regular file: {path}")
        rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    pathlib.Path(args.out).write_text("".join(rows), encoding="utf-8")


def plugin(args):
    source = pathlib.Path(args.source).resolve(strict=True)
    files = collect(source, [p.name for p in source.iterdir()])
    version = json.loads(files["manifest.json"][0])["version"]
    if args.version != f"v{version}" \
            or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("plugin manifest version must match release tag")
    if not 0 <= args.epoch <= 0xFFFFFFFF:
        raise ValueError("epoch must fit the gzip timestamp")
    out = pathlib.Path(args.out).resolve()
    if out.is_relative_to(source):
        raise ValueError("output must not be inside plugin source")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"wisp-plugin-{args.version}.tar.gz"
    archive_files(files, archive, "mirror", args.epoch)
    print(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("bundle", help="stage complete app + Rust sidecar")
    for flag in ("source", "binary", "version", "commit", "out"):
        build.add_argument(f"--{flag}", required=True)
    build.add_argument("--target", choices=TARGETS, required=True)
    build.add_argument("--epoch", type=int, required=True)
    sums = commands.add_parser("checksums", help="write sorted GitHub SHA256SUMS")
    sums.add_argument("--out", required=True)
    sums.add_argument("assets", nargs="+")
    mirror = commands.add_parser("plugin", help="archive an already validated plugin mirror")
    for flag in ("source", "version", "out"):
        mirror.add_argument(f"--{flag}", required=True)
    mirror.add_argument("--epoch", type=int, required=True)
    args = parser.parse_args()
    try:
        {"bundle": bundle, "checksums": checksums, "plugin": plugin}[args.command](args)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f"release build: {error}\n")


if __name__ == "__main__":
    main()
