"""Role guidance for the tool-free controller and native Kanban skill loader."""
from pathlib import Path
import shutil


ROLE_SKILLS = {
    "architect": "workflow-architecture",
    "researcher": "workflow-investigation",
    "builder": "workflow-implementation",
}


def skill_path(role: str) -> Path:
    directory = Path(__file__).resolve().parent / "skills"
    if not directory.is_dir():
        directory = Path(__file__).resolve().parents[1] / "skills"
    return directory / ROLE_SKILLS[role] / "SKILL.md"


def install_worker_skill(profile: Path, role: str) -> None:
    """Copy guidance into a newly created scoped profile, pinning that task's text."""
    if role not in ROLE_SKILLS:
        return
    target = profile / "skills" / ROLE_SKILLS[role] / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".md.tmp")
    shutil.copyfile(skill_path(role), temporary)
    temporary.replace(target)


def architect_guidance() -> str:
    # This entrypoint has no skill_view tool. Read only this operator-owned asset;
    # do not enable tools or load project/default-profile skills into the controller.
    return skill_path("architect").read_text(encoding="utf-8").split("---", 2)[2].strip()
