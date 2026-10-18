# Claude Code -> GitHub Copilot migration kit

Files for the plan -> approve -> execute flow across the UI, Docker (on-prem), AWS, Database and Azure repos.
Model names in the agent files are examples: check the exact names in your Copilot model picker.

| Step | File | Run where | When |
| --- | --- | --- | --- |
| 1. Migrate each repo | `scripts/migrate_repo.py` | your laptop, once per repo | once, dry run first |
| 2. Collect skills | `scripts/sync_skills.py` + `.github/workflows/sync-skills.yml` | central repo, CI | daily and on demand |
| 3. Open the right repos | `workspaces/feature.code-workspace` | VS Code | per feature |
| 4. Pre-flight | `.github/agents/preflight.agent.md` + `scripts/preflight.py` | Copilot chat | start of every feature |
| 5. Design + story | `.github/agents/architect.agent.md` | Copilot chat | after pre-flight |
| 6. Approve | handoff button in the architect (`send: false`) | Copilot chat | human checkpoint |
| 7. Implement | `.github/agents/orchestrator.agent.md` -> `ui`, `data`, `infra` agents | VS Code | after approval |
| 7b. Implement (CLI) | `.github/prompts/fleet-implement.prompt.md` with `/fleet` | Copilot CLI | alternative to 7 |

Entry point: run the `new-feature` prompt (`/new-feature` in chat).

## 1. Migrate a repo

```bash
python3 scripts/migrate_repo.py ../ui            # dry run: shows the plan, writes nothing
python3 scripts/migrate_repo.py ../ui --apply    # writes files + MIGRATION_REPORT.md
```

Nothing under `.claude/` is deleted, so Claude Code keeps working while you test.
Fix everything listed under "Fix inside the files" in the report before testing.

## 2. Collect skills in the central repo

Edit `scripts/repos.txt`, then:

```bash
python3 scripts/sync_skills.py --repos scripts/repos.txt --workdir .. --central .          # dry run
python3 scripts/sync_skills.py --repos scripts/repos.txt --workdir .. --central . --apply
```

Each skill is copied as real files to `.github/skills/<repo>-<skill>` and its `name:` is prefixed the same way.
The workflow does the same daily and opens a PR. It needs a `SKILLS_SYNC_TOKEN` secret with read access to the repos.

## Copy into the central repo

```
.github/agents/*.agent.md
.github/prompts/*.prompt.md
.github/workflows/sync-skills.yml
scripts/
workspaces/
```
