---
name: security-review
description: Replaces Claude Code's built-in /security-review with this repo's security-audit skill. With no arguments it audits the pending changes on the current branch, like the built-in review; with arguments it runs a full security-audit. Usage: /security-review [path] [--config|--code|--all] [--diff[=<base>]]
disable-model-invocation: true
---

# security-review — runs security-audit

A project skill with the same name as a bundled one replaces it, so typing
`/security-review` runs this file instead of the built-in review.

Invoke the `security-audit` skill with the Skill tool. Pass `$ARGUMENTS`
unchanged; when it is empty, pass `--diff` instead, so the scope stays the
built-in review's: the changes on the current branch, not the whole repo.
Follow its steps and report format. Do not run the built-in review or a second
audit of your own.
