#!/usr/bin/env python3
"""Write a local, dated snapshot of public GitHub growth signals.

Fixture mode never invokes gh or the network. Live acquisition is explicit,
read-only and uses the owner's existing gh authentication, never token flags.
"""
import argparse
import json
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path


def github(repo):
    """Read public metadata; unavailable optional data stays unknown."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("expected OWNER/REPO")

    def request(args):
        try:
            result = subprocess.run(["gh", "api"] + args, capture_output=True,
                                    text=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return None

    def get(endpoint, pages=False):
        value = request(["--method", "GET", endpoint]
                        + (["--paginate", "--slurp"] if pages else []))
        if pages and isinstance(value, list):
            return [row for page in value for row in page]
        return value

    base = f"repos/{repo}"
    metadata = get(base)
    if not metadata or metadata.get("private") is not False:
        raise ValueError("public repository metadata unavailable")
    releases = get(base + "/releases?per_page=100", pages=True)
    assets = {}
    for release in releases or []:
        assets[str(release["id"])] = get(
            base + f"/releases/{release['id']}/assets?per_page=100", pages=True)
    owner, name = repo.split("/")
    # GraphQL POST is a read-only query, not a mutation. Counts include
    # closed issues and exclude pull requests, unlike open_issues_count.
    counts = request(["graphql", "-f", "query=query($owner:String!,$name:String!){"
                      "repository(owner:$owner,name:$name){"
                      "issues{totalCount} discussions{totalCount}}}",
                      "-f", f"owner={owner}", "-f", f"name={name}"])
    return {
        "repository": metadata, "releases": releases, "assets": assets,
        "counts": ((counts or {}).get("data") or {}).get("repository"),
        "traffic": {k: get(base + "/traffic/" + k) for k in ("clones", "views")},
    }


def metric(value):
    """Unknown values stay null, not zero."""
    known = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return {"value": value if known else None,
            "status": "available" if known else "unavailable"}


def snapshot(raw, day):
    repo = raw["repository"]
    if repo.get("private") is not False:
        raise ValueError("only public repositories are supported")
    releases, assets = raw.get("releases"), raw.get("assets", {})
    downloads = None
    if isinstance(releases, list) and all(
            isinstance(assets.get(str(r["id"])), list) for r in releases):
        values = [a.get("download_count") for r in releases
                  for a in assets[str(r["id"])]]
        if all(metric(v)["status"] == "available" for v in values):
            downloads = sum(values)
    counts = raw.get("counts") or {}
    traffic = {}
    for kind in ("clones", "views"):
        item = (raw.get("traffic") or {}).get(kind) or {}
        count, uniques = metric(item.get("count")), metric(item.get("uniques"))
        available = count["status"] == uniques["status"] == "available"
        traffic[kind] = {
            "count": count["value"] if available else None,
            "uniques": uniques["value"] if available else None,
            "status": "available" if available else "unavailable",
        }
    return {
        "schema_version": 1, "date": day,
        "repository": repo["full_name"],
        "stars": metric(repo.get("stargazers_count")),
        "forks": metric(repo.get("forks_count")),
        "release_downloads": metric(downloads),
        "issues": metric((counts.get("issues") or {}).get("totalCount")),
        "discussions": metric((counts.get("discussions") or {}).get("totalCount")),
        "traffic": traffic,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", type=Path, help="offline GitHub responses JSON")
    mode.add_argument("--repo", help="explicit live read of public OWNER/REPO")
    parser.add_argument("--date", type=date.fromisoformat,
                        help="snapshot day (fixture date by default)")
    parser.add_argument("--output-dir", type=Path, default=Path("growth-snapshots"))
    args = parser.parse_args(argv)
    try:
        raw = (json.loads(args.fixture.read_text(encoding="utf-8"))
               if args.fixture else github(args.repo))
        day = (args.date or (date.fromisoformat(raw["date"]) if args.fixture
                            else datetime.now(timezone.utc).date())).isoformat()
        data = snapshot(raw, day)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / f"growth-{day}.json"
        target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "growth snapshot failed; check input and output paths.\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
