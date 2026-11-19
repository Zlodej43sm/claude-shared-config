---
name: run-job
description: Run a service job or one-off script (a batch command such as npm run job:<name>) on a deployed environment (UAT, staging, production) or locally against a third-party API, step by step with the user. First loads the project's own job-running doc (pointed to by the root CLAUDE.md / AGENTS.md), checks that the job exists in the project's job scheduler, picks the route (scheduler run or a local run with a temporary scoped key), then walks the dry run → canary → full run → second dry run ladder, reading each log and checking the written records before the next step. Use when asked to run, test or validate a job on an environment, to "run it manually", to add a job to the scheduler, or to do a canary. Usage: /run-job <repo> <job-name> [<env>]
---

# run-job — run a service job safely

Generic and reusable: no company, product or project data lives here. Where jobs are defined, which scheduler runs them on which environment, who may run or edit them and how to get a key for a third party live in the project's docs; this skill reads them first.

## Step 0 — load the project's job doc

1. Read the root `CLAUDE.md` / `AGENTS.md` and follow the pointer to how jobs run (a recipe or runbook on the scheduler, environments, access).
2. Order of authority: project doc → this skill. Where they disagree, the project doc wins.
3. No project doc: ask the user where jobs are defined and run, and offer to write the doc after the run.

## Rules

- The user runs every command that writes to a shared system or uses a secret. You prepare, read logs and check results.
- Never take a key, token or password in the chat. If the user pastes one, do not use it: tell them it is exposed, to delete it and create a new one.
- A secret goes in through a hidden prompt in the user's own terminal: `read -rs <VAR> && export <VAR> && echo "Key set"`. Write every run with `| tee <file>.log` so you can read it; strip auth headers when you print a log.
- A temporary key gets the narrowest scope the third party offers (one application or project, only the endpoints the job calls, expiry tomorrow) and is deleted after the run.
- Stop at the first result you did not predict and ask.

## Steps

1. **Read the job** on the branch that will run: its arguments (write switch, limit), what it calls (database, queue, third parties), what it logs at start and in the summary, and when it exits with a failure code.
2. **Pick the route.**
   - The scheduler has the job for that environment: the user starts it there with the options.
   - It does not: draft the scheduler change from an existing job of the same repo for the user to open. It is needed for production anyway.
   - The job calls only a third-party API and the user wants to run it now: local run with a temporary scoped key. Show the key form if a browser is available, but let the user fill and save it.
   - Check what code the environment runs (the scheduler often uses the deployed image): another deploy can remove the job before your run.
3. **Prepare a local run.** Detached worktree on `origin/<branch>`, install from the lock file, build, confirm the built entry file exists. If the package manager rejects the lock file for missing platform packages, install without it, then restore the lock file from git.
4. **Hand over commands one at a time**, each in its own block: change directory, export the non-secret config, the hidden key prompt, then the job with `| tee`. Say what the user should see after each one.
5. **Run ladder.** After each step read the log and check:
   - **Dry run** (no write): the target IDs in the start line, the counts, no 401/403/400. Explain every failed or skipped item before going on.
   - **Canary** (write with a small limit): read the written records back (API GET into a file, or the UI) and compare every field, not only the one meant to change. Check the downstream sync (webhook, database row) when the job feeds one.
   - **Full run**: counts add up with the dry run minus the canary; no abort.
   - **Second dry run**: nothing left to do, so the job is safe to run again.
6. **Record and clean up.** Counts per run, duration, IDs of failed items (no codes, no personal data) in the ticket's run notes. Then: `unset` the key, the user deletes it at the third party, remove the worktree and logs, close the terminal tabs you opened.
7. **Report.** Offer drafts for the PR description (`pr-description` skill: results under "how to verify") and the team thread. Name open decisions, such as items the job skips by design, for the data owner. Before a production write, ask for the data owner's go-ahead and a low-traffic window for a long run.

## Explaining it to the user

- **Dry run:** the job only reads and counts what it would change.
- **Canary:** the real job on a few records only, checked by hand before the full run. If it is wrong, only those few are wrong.
- **Second dry run:** proves the job is finished and safe to run again.
