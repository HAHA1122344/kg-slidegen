#!/usr/bin/env python3
"""Recreate this repository on GitHub through the REST API instead of ``git push``.

Why this exists: on this machine ``https://github.com`` is unreachable (the
local proxy answers ``502`` to the CONNECT for that host, while
``api.github.com`` works), so ``git push`` cannot upload a pack. Git objects are
content-addressed, so the history can be rebuilt exactly through the API---same
blob bytes, same tree entries, same author/committer lines and dates---and the
resulting commit SHAs are the ones the local repository already has. After the
import, ``git fetch origin`` matches with no divergence.

Run from the repository root:

    python scripts/import_via_api.py --repo owner/name --dry-run
    python scripts/import_via_api.py --repo owner/name

Idempotent enough to re-run on a fresh empty repository; it refuses to run if the
remote already has commits.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def git_text(*args: str) -> str:
    return git(*args).decode("utf-8", "surrogateescape")


def token() -> str:
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


class Api:
    def __init__(self, repo: str, dry_run: bool = False) -> None:
        self.base = f"https://api.github.com/repos/{repo}"
        self.dry_run = dry_run
        self.calls = 0
        self.retries = 0
        self._token = token()

    def __call__(self, method: str, path: str, payload: dict | None = None) -> dict:
        if self.dry_run:
            self.calls += 1
            return {"sha": "0" * 40}
        body = json.dumps(payload).encode() if payload is not None else None

        # Everything is retried, not only 5xx: behind the proxy on this machine a
        # CONNECT to api.github.com intermittently answers 502, drops the TLS
        # session mid-read (UNEXPECTED_EOF) or stalls past the timeout, and a
        # 1.4 MB blob upload can come back as a 400 "malformed request" that
        # succeeds unchanged on the next attempt.  A blob upload is idempotent by
        # construction -- the response sha is derived from the bytes -- so
        # retrying it cannot duplicate anything.
        attempts = 7
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.base + path,
                method=method,
                data=body,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "User-Agent": "kg-slidegen-import",
                },
            )
            last = attempt == attempts - 1
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    self.calls += 1
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # 4xx other than 429 are our own fault and will not heal.
                if exc.code not in (400, 408, 429, 500, 502, 503, 504) or last:
                    raise SystemExit(f"{method} {path} -> {exc.code}: {detail}")
                reason = f"HTTP {exc.code}: {detail[:120]}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if last:
                    raise SystemExit(f"{method} {path} -> {exc}")
                reason = str(exc)
            self.retries += 1
            time.sleep(min(2 ** attempt, 30))
            print(f"    retry {attempt + 1}/{attempts - 1} {method} {path}: {reason}", flush=True)
        raise SystemExit("unreachable")


def parse_commit(sha: str) -> dict:
    """Split a raw commit object into the fields the API needs back."""
    raw = git_text("cat-file", "commit", sha)
    header, _, message = raw.partition("\n\n")
    fields: dict[str, str] = {}
    parents: list[str] = []
    for line in header.splitlines():
        if line.startswith("parent "):
            parents.append(line.split(" ", 1)[1])
        elif " " in line:
            key, value = line.split(" ", 1)
            fields.setdefault(key, value)
    if "encoding" in fields:
        raise SystemExit(
            f"commit {sha} carries an encoding header; the API cannot reproduce it"
        )
    author_name, author_email, author_ts = split_ident(fields["author"])
    committer_name, committer_email, committer_ts = split_ident(fields["committer"])
    return {
        "sha": sha,
        "tree": fields["tree"],
        "parents": parents,
        # Kept byte-for-byte: a normalised message changes the commit sha.
        "message": message,
        "author": {
            "name": author_name,
            "email": author_email,
            "date": iso_date(author_ts),
        },
        "committer": {
            "name": committer_name,
            "email": committer_email,
            "date": iso_date(committer_ts),
        },
    }


def split_ident(line: str) -> tuple[str, str, str]:
    name, _, rest = line.partition(" <")
    email, _, stamp = rest.rpartition("> ")
    return name, email, stamp


def iso_date(raw_stamp: str) -> str:
    seconds, _, offset = raw_stamp.partition(" ")
    sign = -1 if offset.startswith("-") else 1
    hours, minutes = int(offset[1:3]), int(offset[3:5])
    tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    return datetime.fromtimestamp(int(seconds), tz).isoformat()


def tree_entries(sha: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, object sha) for every entry in a commit's tree."""
    entries: dict[str, tuple[str, str]] = {}
    for line in git_text("ls-tree", "-r", "-z", sha).split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        mode, kind, obj = meta.split()
        if kind != "blob":
            raise SystemExit(f"{path} is a {kind}; submodules are not supported here")
        entries[path] = (mode, obj)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs", type=int, default=3,
                        help="parallel blob uploads (lower it when the proxy stalls)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the branch even if it has commits (needed after bootstrapping "
             "an empty repository, where git-data endpoints answer 409 until one exists)",
    )
    parser.add_argument(
        "--since",
        metavar="SHA",
        help="a commit already imported that the remote still has; blobs reachable "
             "from it are assumed present and are not re-uploaded.  Blob shas are "
             "content-addressed, so a skipped blob's remote sha is its local one.",
    )
    args = parser.parse_args()

    api = Api(args.repo, dry_run=args.dry_run)

    if not args.dry_run and not args.force:
        try:
            existing = api("GET", "/git/ref/heads/" + args.branch)
            sha = existing.get("object", {}).get("sha")
            print(f"ref {args.branch} already exists at {sha}")
            print("refusing to import into a non-empty branch")
            return 1
        except SystemExit:
            pass  # 404 is what we want

    commits = git_text("rev-list", "--reverse", "HEAD").split()
    print(f"{len(commits)} commits, HEAD tree {git_text('rev-parse', 'HEAD^{tree}').strip()[:12]}")

    parsed = [parse_commit(sha) for sha in commits]
    trees = {sha: tree_entries(sha) for sha in commits}

    # Every distinct blob in the history, uploaded once.
    blobs: dict[str, str] = {}
    for entries in trees.values():
        for _mode, obj in entries.values():
            blobs.setdefault(obj, "")

    # With --since, everything already on the remote is taken as present.  This
    # is what makes a second import cheap: this history is 189 blobs and about
    # 7 MB, nearly all of it unchanged, and each unchanged PDF is a 1.4 MB POST
    # through the flaky proxy.
    if args.since:
        # The whole ancestry, not just the tip tree: earlier versions of a file
        # are distinct blobs, and they are on the remote too.
        present: set[str] = set()
        for sha in git_text("rev-list", args.since).split():
            present.update(obj for _mode, obj in tree_entries(sha).values())
        for obj in list(blobs):
            if obj in present:
                blobs[obj] = obj
        print(f"{len(present & set(blobs))} blobs already at {args.since[:8]}, "
              f"{sum(1 for v in blobs.values() if not v)} to upload")

    def upload(obj: str) -> tuple[str, str]:
        if api.dry_run:
            return obj, obj
        if blobs[obj]:
            return obj, blobs[obj]  # skipped by --since
        content = git("cat-file", "blob", obj)
        result = api(
            "POST",
            "/git/blobs",
            {"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
        return obj, result["sha"]

    print(f"uploading {len(blobs)} blobs ...")
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for local, remote in pool.map(upload, blobs):
            if local != remote:
                raise SystemExit(f"blob sha mismatch {local} -> {remote}")
            blobs[local] = remote

    # Trees and commits, oldest first, so each parent exists when it is needed.
    previous_tree: str | None = None
    previous_map: dict[str, tuple[str, str]] = {}
    previous_commit: str | None = None
    for commit in parsed:
        current = trees[commit["sha"]]
        entries = []
        for path, (mode, obj) in current.items():
            if previous_map.get(path) != (mode, obj):
                entries.append({"path": path, "mode": mode, "type": "blob", "sha": blobs[obj]})
        for path in previous_map:
            if path not in current:
                entries.append(
                    {"path": path, "mode": previous_map[path][0], "type": "blob", "sha": None}
                )
        payload: dict = {"tree": entries}
        if previous_tree:
            payload["base_tree"] = previous_tree
        tree = api("POST", "/git/trees", payload)
        if tree["sha"] != commit["tree"] and not api.dry_run:
            raise SystemExit(
                f"tree mismatch for {commit['sha'][:8]}: {tree['sha']} != {commit['tree']}"
            )

        body = {
            "message": commit["message"],
            "tree": tree["sha"],
            "parents": [previous_commit] if previous_commit else [],
            "author": commit["author"],
            "committer": commit["committer"],
        }
        made = api("POST", "/git/commits", body)
        if made["sha"] != commit["sha"] and not api.dry_run:
            raise SystemExit(
                f"commit mismatch {commit['sha'][:8]}: got {made['sha'][:8]}"
            )
        print(f"  {commit['sha'][:8]} {commit['message'].splitlines()[0][:60]}")
        previous_tree, previous_map, previous_commit = tree["sha"], current, made["sha"]

    if args.force:
        api(
            "PATCH",
            f"/git/refs/heads/{args.branch}",
            {"sha": previous_commit, "force": True},
        )
    else:
        api("POST", "/git/refs", {"ref": f"refs/heads/{args.branch}", "sha": previous_commit})
    print(f"\nimported {len(parsed)} commits, {api.calls} API calls, head {previous_commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
