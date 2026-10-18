#!/usr/bin/env python3
"""
migrate_repo.py - migrate one repo's Claude Code setup to GitHub Copilot.

Dry run by default: prints the plan and changes nothing.
Run with --apply to write the files and MIGRATION_REPORT.md. Claude files are never deleted,
so Claude Code keeps working side by side during the transition.

  python3 migrate_repo.py ../ui-repo            # dry run
  python3 migrate_repo.py ../ui-repo --apply    # write files

What it does
  1. CLAUDE.md (any folder)     -> AGENTS.md next to it, @imports inlined
  2. .claude/skills/<name>/     -> .github/skills/<name>/  + lint of SKILL.md
  3. .claude/agents/*.md        -> .github/agents/<name>.agent.md
  4. .claude/commands/**/*.md   -> .github/prompts/<name>.prompt.md
  5. .mcp.json                  -> .vscode/mcp.json  (mcpServers -> servers)
  6. .claude/settings.json      -> report only (hooks and permissions need a manual rewrite)
"""
import argparse, json, re, shutil, sys
from pathlib import Path

CLAUDE_TOOLS = r"\b(Bash|Read|Write|Edit|MultiEdit|Grep|Glob|Task|TodoWrite|WebFetch|WebSearch|NotebookEdit)\b(?=\s*(tool|\(|to\b|for\b))"
MODEL_MAP = {  # Claude Code aliases -> Copilot model names. Check the exact names in your model picker.
    "opus": "Claude Opus 5.5",
    "sonnet": "Claude Sonnet 5",
    "haiku": "Claude Haiku 5.5",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".terraform"}


class Plan:
    def __init__(self, root: Path, apply: bool):
        self.root, self.apply = root, apply
        self.actions, self.warnings, self.manual = [], [], []

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    def write(self, dest: Path, text: str, why: str):
        if dest.exists():
            self.warnings.append(f"{self.rel(dest)} exists, not overwritten ({why})")
            return
        self.actions.append(f"write  {self.rel(dest)}  <- {why}")
        if self.apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")

    def copytree(self, src: Path, dest: Path):
        if dest.exists():
            self.warnings.append(f"{self.rel(dest)} exists, not overwritten")
            return
        self.actions.append(f"copy   {self.rel(src)}/ -> {self.rel(dest)}/")
        if self.apply:
            shutil.copytree(src, dest, symlinks=False)  # resolve symlinks into real files


def walk(root: Path, name: str):
    for p in root.rglob(name):
        if not any(part in SKIP_DIRS for part in p.parts):
            yield p


def split_frontmatter(text: str):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip("'\"")
    return fm, m.group(2)


def lint_text(plan: Plan, where: str, body: str, fm: dict, is_skill=False):
    if is_skill:
        if not fm.get("name") or not fm.get("description"):
            plan.warnings.append(f"{where}: missing name or description in frontmatter -> it will be read as a plain file, not a skill")
        elif len(fm["description"]) < 40:
            plan.warnings.append(f"{where}: description is very short -> write 'Use when ...' with the words developers type")
    if "allowed-tools" in fm:
        plan.warnings.append(f"{where}: 'allowed-tools' is Claude-only -> move tool limits to a custom agent's tools:")
    for hit in sorted(set(m.group(1) for m in re.finditer(CLAUDE_TOOLS, body))):
        plan.warnings.append(f"{where}: names the Claude tool '{hit}' -> describe the action instead")
    if "$ARGUMENTS" in body:
        plan.warnings.append(f"{where}: uses $ARGUMENTS -> pass arguments in the prompt or use ${{input:args}}")
    if "~/.claude" in body or ".claude/" in body:
        plan.warnings.append(f"{where}: refers to a .claude path -> check it still resolves")
    for m in re.finditer(r"(?<![\w/])@([\w./-]+\.(md|txt|json|ya?ml))", body):
        plan.warnings.append(f"{where}: reference '@{m.group(1)}' -> Copilot reads it as text and may open the file itself")


def inline_imports(plan: Plan, md: Path, depth=0) -> str:
    text = md.read_text(encoding="utf-8")
    if depth > 3:
        return text

    def repl(m):
        target = m.group(1)
        p = Path(target).expanduser()
        p = p if p.is_absolute() else (md.parent / p)
        if p.is_file():
            plan.actions.append(f"inline {plan.rel(p)} into AGENTS.md (from {plan.rel(md)})")
            return f"\n<!-- inlined from {target} -->\n" + inline_imports(plan, p, depth + 1) + "\n"
        plan.warnings.append(f"{plan.rel(md)}: @{target} not found, left as text")
        return m.group(0)

    return re.sub(r"(?m)^\s*@([~\w./-]+)\s*$", repl, text)


def step_instructions(plan: Plan):
    for md in walk(plan.root, "CLAUDE.md"):
        agents = md.with_name("AGENTS.md")
        body = inline_imports(plan, md)
        plan.write(agents, body, f"{plan.rel(md)}")
        lint_text(plan, plan.rel(md), body, {})


def step_skills(plan: Plan):
    src_root = plan.root / ".claude" / "skills"
    if not src_root.is_dir():
        return
    for skill in sorted(p for p in src_root.iterdir() if p.is_dir()):
        sk = skill / "SKILL.md"
        if not sk.is_file():
            plan.warnings.append(f"{plan.rel(skill)}: no SKILL.md -> not a skill")
            continue
        if skill.is_symlink():
            plan.warnings.append(f"{plan.rel(skill)}: symlink -> copied as real files")
        fm, body = split_frontmatter(sk.read_text(encoding="utf-8"))
        lint_text(plan, plan.rel(sk), body, fm, is_skill=True)
        plan.copytree(skill, plan.root / ".github" / "skills" / skill.name)


def step_agents(plan: Plan):
    src = plan.root / ".claude" / "agents"
    if not src.is_dir():
        return
    for f in sorted(src.glob("*.md")):
        fm, body = split_frontmatter(f.read_text(encoding="utf-8"))
        name = fm.get("name") or f.stem
        model = MODEL_MAP.get(fm.get("model", "").lower(), fm.get("model") or "")
        lines = ["---", f"name: {name}", f"description: {fm.get('description', 'TODO: when to use this agent')}"]
        lines.append(f"model: {model}" if model else "# model: TODO pin a model for this agent")
        if fm.get("tools"):
            lines.append(f"# tools: TODO map to Copilot tools. Claude tools were: {fm['tools']}")
        lines.append("---")
        lint_text(plan, plan.rel(f), body, fm)
        plan.write(plan.root / ".github" / "agents" / f"{name}.agent.md", "\n".join(lines) + "\n" + body, plan.rel(f))


def step_commands(plan: Plan):
    src = plan.root / ".claude" / "commands"
    if not src.is_dir():
        return
    for f in sorted(src.rglob("*.md")):
        fm, body = split_frontmatter(f.read_text(encoding="utf-8"))
        name = "-".join(f.relative_to(src).with_suffix("").parts)
        body = body.replace("$ARGUMENTS", "${input:args}")
        body = re.sub(r"\$(\d)\b", r"${input:arg\1}", body)
        desc = fm.get("description") or (body.strip().splitlines() or ["TODO"])[0][:120]
        text = f"---\ndescription: {desc}\n---\n{body}"
        plan.write(plan.root / ".github" / "prompts" / f"{name}.prompt.md", text, plan.rel(f))


def step_mcp(plan: Plan):
    src = plan.root / ".mcp.json"
    if not src.is_file():
        return
    data = json.loads(src.read_text(encoding="utf-8"))
    servers = {}
    for name, s in data.get("mcpServers", {}).items():
        out = dict(s)
        out.setdefault("type", "http" if "url" in s else "stdio")
        if out["type"] == "sse":
            plan.warnings.append(f".mcp.json: server '{name}' uses SSE -> check it is still supported, prefer http")
        for key in ("env", "headers"):
            if key in out:
                out[key] = {k: re.sub(r"\$\{(\w+)\}", r"${env:\1}", str(v)) for k, v in out[key].items()}
        servers[name] = out
    plan.write(plan.root / ".vscode" / "mcp.json", json.dumps({"servers": servers}, indent=2) + "\n", ".mcp.json")
    plan.manual.append("CLI users: add the same servers to ~/.copilot/mcp-config.json; cloud agent: repo Settings > Copilot > MCP")


def step_settings(plan: Plan):
    for name in ("settings.json", "settings.local.json"):
        f = plan.root / ".claude" / name
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan.warnings.append(f"{plan.rel(f)}: not valid JSON")
            continue
        for event, hooks in (data.get("hooks") or {}).items():
            plan.manual.append(f"{plan.rel(f)}: hook '{event}' -> rewrite as a Copilot hook, or move into preflight.agent.md ({json.dumps(hooks)[:160]})")
        perms = data.get("permissions") or {}
        for kind in ("allow", "deny", "ask"):
            if perms.get(kind):
                plan.manual.append(f"{plan.rel(f)}: permissions.{kind} = {perms[kind]} -> VS Code tool approval settings / CLI --allow-tool, --deny-tool")
        if data.get("model"):
            plan.manual.append(f"{plan.rel(f)}: default model '{data['model']}' -> model: in each .agent.md, or COPILOT_MODEL")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", type=Path)
    ap.add_argument("--apply", action="store_true", help="write the files (default is a dry run)")
    a = ap.parse_args()
    root = a.repo.resolve()
    if not root.is_dir():
        sys.exit(f"not a folder: {root}")
    plan = Plan(root, a.apply)
    for step in (step_instructions, step_skills, step_agents, step_commands, step_mcp, step_settings):
        step(plan)

    mode = "APPLIED" if a.apply else "DRY RUN (nothing written, run with --apply)"
    report = [f"# Migration report: {root.name}", "", f"Mode: {mode}", "",
              "## Files", *[f"- {x}" for x in plan.actions or ["nothing to migrate"]], "",
              "## Fix inside the files", *[f"- {x}" for x in plan.warnings or ["none"]], "",
              "## Manual steps", *[f"- {x}" for x in plan.manual or ["none"]], ""]
    text = "\n".join(report)
    print(text)
    if a.apply:
        (root / "MIGRATION_REPORT.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
