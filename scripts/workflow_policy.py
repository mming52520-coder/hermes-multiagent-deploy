"""Pre-authorized scope for automatic acceptance, and the human decision log.

A change set inside the scope is accepted without a human click once the
platform receipt and Reviewer PASS are valid. Anything listed here is a human
decision and is pushed to the single decision channel.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import time

# Paths whose change is a human decision regardless of test results.
# Categories follow the report: data/schema, CI/deploy/permissions,
# credentials, and new dependencies.
DEFAULT_SENSITIVE = {
    "数据库结构或迁移": ("*migrations/*", "*migrate/*", "*.sql", "*schema.prisma", "*alembic/*"),
    "CI、部署或权限配置": (".github/*", ".gitlab-ci.yml", "Jenkinsfile", "Dockerfile*", "*docker-compose*",
                         "deploy/*", "k8s/*", "helm/*", "terraform/*", "*.tf", "CODEOWNERS", ".github/CODEOWNERS"),
    "密钥或凭据": (".env*", "*.pem", "*.key", "*secret*", "*credential*", "*.p12"),
    "新增或升级依赖": ("package.json", "*/package.json", "package-lock.json", "*/package-lock.json",
                   "pnpm-lock.yaml", "yarn.lock", "requirements*.txt", "*/requirements*.txt", "pyproject.toml",
                   "*/pyproject.toml", "poetry.lock", "uv.lock", "Pipfile*", "go.mod", "go.sum", "Cargo.toml",
                   "Cargo.lock", "Gemfile*", "pom.xml", "build.gradle*"),
}


def policy_from_env(env: dict) -> dict:
    """Snapshot the operator's policy when an execution is created."""
    extra = [item.strip() for item in env.get("WORKFLOW_DECISION_PATHS", "").split(",") if item.strip()]
    return {
        "auto_accept": env.get("WORKFLOW_AUTO_ACCEPT", "false").strip().lower() in {"1", "true", "yes"},
        "max_auto_files": int(env.get("WORKFLOW_AUTO_ACCEPT_MAX_FILES", "20") or 20),
        "extra_paths": extra,
    }


def _matches(path: str, pattern: str) -> bool:
    path, pattern = path.lower(), pattern.lower()
    return fnmatch(path, pattern) or ("/" not in pattern and fnmatch(Path(path).name, pattern))


def decision_reasons(policy: dict | None, changed: list[str], deleted: list[str]) -> list[dict]:
    """Return why this change set needs a human; empty means pre-authorized."""
    if not policy or not policy.get("auto_accept"):
        return [{"category": "未开启自动验收", "paths": []}]
    reasons = []
    categories = dict(DEFAULT_SENSITIVE)
    if policy.get("extra_paths"):
        categories["操作员指定的路径"] = tuple(policy["extra_paths"])
    for category, patterns in categories.items():
        hits = sorted(path for path in changed if any(_matches(path, pattern) for pattern in patterns))
        if hits:
            reasons.append({"category": category, "paths": hits})
    if deleted:
        reasons.append({"category": "删除文件", "paths": sorted(deleted)})
    if len(changed) > policy.get("max_auto_files", 20):
        reasons.append({"category": f"改动文件超过 {policy.get('max_auto_files', 20)} 个", "paths": []})
    return reasons


DECISION_FILES = {"approved": ("approved.md", "已定的事"), "rejected": ("rejected.md", "定了不做的事")}


def decisions_directory(root: Path, board: str) -> Path:
    # Kept with operator records, not in the project: the source must stay clean.
    return Path(root) / "workflow" / "decisions" / board


def record_decision(root: Path, board: str, kind: str, *, execution: str, objective: str, text: str) -> Path:
    """Append the human's decision with the original wording and date."""
    name, title = DECISION_FILES[kind]
    directory = decisions_directory(root, board)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / name
    if not target.exists():
        target.write_text(f"# {title}\n\n只记录人的原话和日期。Agent 规划前读取，同类问题不再重复询问。可直接编辑。\n\n",
                          encoding="utf-8")
    heading = objective.strip().splitlines()[0][:80] if objective.strip() else execution[:8]
    when = time.strftime("%Y-%m-%d", time.localtime())
    quoted = "\n".join("> " + line for line in text.strip().splitlines()) or "> （未填写原话）"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(f"## {when} · {heading}\n\n{quoted}\n\n执行：`{execution}`\n\n")
    return target


def read_decisions(root: Path, board: str, limit: int = 6000) -> dict:
    """Most recent decisions first fit within ``limit`` characters per file."""
    result = {}
    for kind, (name, _title) in DECISION_FILES.items():
        target = decisions_directory(root, board) / name
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        result[kind] = text[-limit:] if len(text) > limit else text
    return result
