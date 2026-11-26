#!/usr/bin/env python3
"""
azure_repo — resolve Azure DevOps PR coordinates for the PR skills (host=azure).
The skills read and post through the `azure-devops` MCP server; this tool only
parses URLs and finds the local clone the reviewer reads code and diffs from.

SCHEMA_IN
  parse-url <url>    a PR URL: https://dev.azure.com/<org>/<project>/_git/<repo>/pullrequest/<id>
                     or https://<org>.visualstudio.com/<project>/_git/<repo>/pullrequest/<id>
                     (trailing path / query is fine)
  origin [<dir>]     the origin remote of <dir> (default: cwd)
  env                org/project/repo for this project: each from AZURE_DEVOPS_ORG / _PROJECT /
                     _REPO, else AZURE_DEVOPS_URL, else the origin remote (process env first,
                     then the project's .claude/.env; hooks/sync-env.py azure_settings)
  org                the org alone, plain text: mcp-run.py's --fallback for AZURE_DEVOPS_ORG
  find-clone --org=O --project=P --repo=R
                     looks for a clone whose origin is that repo: cwd, $CLAUDE_PROJECT_DIR,
                     then their direct subdirectories (a multi-repo workspace root)

SCHEMA_OUT  stdout JSON
  parse-url   {"org", "project", "repo", "pr_id"}        project/repo URL-decoded
  origin      {"org", "project", "repo"}
  env         {"org", "project", "repo"}                  "" for a part no source has
  org         <org>                                       plain text
  find-clone  {"repo_dir": "/abs/path"}

EXIT  0=ok  1=not found / not an Azure DevOps URL  2=bad arguments
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def load_sync_env():
    # hooks/sync-env.py owns the Azure remote patterns; reuse them (as mcp-run.py does).
    path = Path(__file__).resolve().parent.parent / "hooks" / "sync-env.py"
    spec = importlib.util.spec_from_file_location("sync_env", path)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


SYNC_ENV = load_sync_env()
PR_ID = re.compile(r"/pullrequest/(\d+)")


def fail(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"azure_repo: {msg}\n")
    raise SystemExit(code)


def slug_of(directory: Path) -> tuple[str, str, str] | None:
    if not (directory / ".git").exists():
        return None
    return SYNC_ENV.azure_remote_slug(SYNC_ENV.origin_url(str(directory)))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="azure_repo.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_url = sub.add_parser("parse-url")
    p_url.add_argument("url")
    p_origin = sub.add_parser("origin")
    p_origin.add_argument("dir", nargs="?", default=".")
    sub.add_parser("env")
    sub.add_parser("org")
    p_find = sub.add_parser("find-clone")
    p_find.add_argument("--org", required=True)
    p_find.add_argument("--project", required=True)
    p_find.add_argument("--repo", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "parse-url":
        base = args.url.split("/pullrequest/")[0]
        slug = SYNC_ENV.azure_remote_slug(base)
        pr = PR_ID.search(args.url)
        if not slug or not pr:
            fail(f"not an Azure DevOps pull request URL: {args.url!r}")
        org, project, repo = slug
        print(json.dumps({"org": org, "project": project, "repo": repo, "pr_id": int(pr.group(1))}))
        return 0

    if args.cmd == "origin":
        slug = SYNC_ENV.azure_remote_slug(SYNC_ENV.origin_url(args.dir))
        if not slug:
            fail(f"origin of {args.dir!r} is not an Azure DevOps remote")
        print(json.dumps(dict(zip(("org", "project", "repo"), slug))))
        return 0

    if args.cmd in ("env", "org"):
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
        env_file = next((d / ".claude" / ".env" for d in (Path.cwd(), root) if (d / ".claude" / ".env").is_file()), None)
        env = SYNC_ENV.parse_env_file(env_file) if env_file else {}
        env.update({k: v for k, v in os.environ.items() if k.startswith("AZURE_DEVOPS_") and v})
        resolved = SYNC_ENV.azure_settings(env)
        org, project, repo = (resolved[k] for k in SYNC_ENV.AZURE_KEYS)
        if args.cmd == "org":
            if not org:
                fail("no Azure DevOps org: set AZURE_DEVOPS_ORG or AZURE_DEVOPS_URL in .claude/.env")
            print(org)
        else:
            print(json.dumps({"org": org, "project": project, "repo": repo}))
        return 0

    wanted = tuple(v.lower() for v in (args.org, args.project, args.repo))
    roots = [Path.cwd()]
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        roots.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
    candidates = roots + [child for root in roots if root.is_dir()
                          for child in sorted(root.iterdir()) if child.is_dir()]
    for directory in candidates:
        slug = slug_of(directory)
        if slug and tuple(v.lower() for v in slug) == wanted:
            print(json.dumps({"repo_dir": str(directory.resolve())}))
            return 0
    fail(f"no local clone of {args.org}/{args.project}/{args.repo} in {', '.join(map(str, roots))} "
         "or their subdirectories — clone it, or run from inside the clone")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
