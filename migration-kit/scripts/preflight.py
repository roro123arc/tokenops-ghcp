#!/usr/bin/env python3
"""
preflight.py - the checks that run before every feature: pull every repo
and flag possible breaking changes. The preflight agent runs this script
and reads its JSON output, then asks the developer what to do.

  python3 scripts/preflight.py --repos scripts/repos.txt --workdir ..

Breaking-change heuristic: files changed by the pull that match CONTRACT
patterns (API specs, DB migrations, IaC, Docker). Tune the list per repo.
"""
import argparse, fnmatch, json, subprocess
from pathlib import Path

CONTRACT = [
    "*openapi*.y*ml", "*swagger*", "*.proto", "*.graphql",      # APIs
    "*migrations/*", "*.sql", "*schema*",                        # Database
    "*.tf", "*.bicep", "*cloudformation*", "*cdk*",              # AWS / Azure IaC
    "Dockerfile*", "*docker-compose*", "*helm/*", "*charts/*",   # Docker on-prem
    "package.json", "*.csproj", "pyproject.toml", "go.mod",      # dependencies
]


def git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("--workdir", type=Path, default=Path(".."))
    ap.add_argument("--no-pull", action="store_true", help="only report, do not pull")
    a = ap.parse_args()

    out = []
    for line in a.repos.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        prefix, src = line.split(maxsplit=1)
        path = Path(src).expanduser() if Path(src).expanduser().is_dir() else a.workdir / prefix
        item = {"repo": prefix, "path": str(path)}
        if not (path / ".git").exists():
            item["error"] = "not cloned - run sync_skills.py --apply first"
            out.append(item)
            continue
        _, before, _ = git("rev-parse", "HEAD", cwd=path)
        _, dirty, _ = git("status", "--porcelain", cwd=path)
        item["uncommitted_changes"] = bool(dirty)
        if not a.no_pull and not dirty:
            code, _, err = git("pull", "--ff-only", cwd=path)
            if code:
                item["pull_error"] = err
        _, after, _ = git("rev-parse", "HEAD", cwd=path)
        changed = []
        if before != after:
            _, files, _ = git("diff", "--name-only", f"{before}..{after}", cwd=path)
            changed = files.splitlines()
        item["new_commits"] = before != after
        item["changed_files"] = len(changed)
        item["possible_breaking"] = [f for f in changed if any(fnmatch.fnmatch(f, p) for p in CONTRACT)]
        out.append(item)

    print(json.dumps({"repos": out,
                      "needs_attention": [r["repo"] for r in out
                                          if r.get("possible_breaking") or r.get("error") or r.get("pull_error") or r.get("uncommitted_changes")]},
                     indent=2))


if __name__ == "__main__":
    main()
