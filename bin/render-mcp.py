#!/usr/bin/env python3
"""
Render a project's .mcp.json to stdout: mcp.json.template (always) plus the
fragments from mcp.d/ that match what the project actually uses.

  - github      when the git host resolves to "github" (same resolution as
                tools/detect_git_host.sh / hooks/sync-env.py: GIT_HOST, then the
                origin remote URL, then BITBUCKET_WORKSPACE/GITHUB_OWNER).
                github.com -> hosted MCP endpoint (no docker needed);
                GITHUB_API_URL set to an enterprise endpoint -> the docker
                github-mcp-server pointed at that host.
  - (nothing)   when the host is "bitbucket": there is no Bitbucket MCP server,
                the PR skills talk to Bitbucket through tools/bb_*.sh instead.
  - notion      when NOTION_TOKEN is set (and not a placeholder) in .claude/.env.

Usage: bin/render-mcp.py <project_path>
Diagnostics go to stderr, the JSON document to stdout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

SHARED_DIR = Path(__file__).resolve().parent.parent


def load_sync_env():
    # hooks/sync-env.py owns the .env parser and the host-detection logic;
    # reuse it so the two can never disagree about which host a project uses.
    spec = importlib.util.spec_from_file_location("sync_env", SHARED_DIR / "hooks" / "sync-env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enterprise_host(api_url: str) -> str | None:
    """Map GITHUB_API_URL to the web host github-mcp-server expects in GITHUB_HOST.
    None for github.com itself."""
    if not api_url:
        return None
    parts = urlsplit(api_url)
    netloc = parts.netloc
    if not netloc or netloc == "api.github.com":
        return None
    if netloc.startswith("api.") and netloc.endswith(".ghe.com"):  # GHEC data residency
        netloc = netloc[len("api."):]
    return f"{parts.scheme or 'https'}://{netloc}"


def load_fragment(name: str) -> dict:
    return json.loads((SHARED_DIR / "mcp.d" / name).read_text(encoding="utf-8"))


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: render-mcp.py <project_path>\n")
        return 2
    project = Path(sys.argv[1]).resolve()
    sync_env = load_sync_env()

    env: dict[str, str] = {}
    env_path = project / ".claude" / ".env"
    if env_path.is_file():
        env = sync_env.parse_env_file(env_path)

    os.chdir(project)  # detect_git_host reads `git remote get-url origin` from the cwd
    host = sync_env.detect_git_host(env)

    config = json.loads((SHARED_DIR / "mcp.json.template").read_text(encoding="utf-8"))
    servers = config["mcpServers"]
    added = []

    if host == "github":
        ghes = enterprise_host(env.get("GITHUB_API_URL", "").strip())
        if ghes:
            fragment = json.loads(
                json.dumps(load_fragment("github-enterprise.json")).replace("__GITHUB_HOST__", ghes)
            )
            added.append(f"github (enterprise: {ghes})")
        else:
            fragment = load_fragment("github.json")
            added.append("github")
        servers.update(fragment)
    elif host is None:
        sys.stderr.write(
            "[render-mcp] git host undetermined (no origin remote, no GIT_HOST) — "
            "no git MCP server added; re-run link-project.sh once it is set.\n"
        )

    notion_token = env.get("NOTION_TOKEN", "").strip()
    if notion_token and not sync_env.looks_like_placeholder(notion_token):
        servers.update(load_fragment("notion.json"))
        added.append("notion")

    sys.stderr.write(
        f"[render-mcp] git host: {host or 'unknown'}; added: {', '.join(added) if added else 'none'}\n"
    )
    json.dump(config, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
