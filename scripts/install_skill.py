from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILL_NAME = "yt-bundle"


def default_skill_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "skills"
    return Path.home() / ".codex" / "skills"


def parse_args() -> argparse.Namespace:
    examples = """Examples:
  python3 scripts/install_skill.py
  python3 scripts/install_skill.py --target-dir ~/.codex/skills
  python3 scripts/install_skill.py --target-dir /tmp/skill-test
  python3 scripts/install_skill.py --force
"""
    parser = argparse.ArgumentParser(
        description="Install the yt-bundle Codex skill from this repository into a skills directory.",
        epilog=examples,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--skill-name",
        default=DEFAULT_SKILL_NAME,
        help=f"Skill directory name under skills/. Defaults to {DEFAULT_SKILL_NAME}.",
    )
    parser.add_argument(
        "--source-dir",
        default=str(REPO_ROOT / "skills"),
        help="Directory that contains the repository-backed skill folders. Defaults to ./skills in this repository.",
    )
    parser.add_argument(
        "--target-dir",
        default=str(default_skill_root()),
        help="Destination skills root. Defaults to $CODEX_HOME/skills or ~/.codex/skills.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing installed skill. The previous version is moved to a timestamped backup first.",
    )
    return parser.parse_args()


def install_skill(source_root: Path, target_root: Path, skill_name: str, force: bool) -> Path:
    source_dir = source_root / skill_name
    if not source_dir.exists():
        raise FileNotFoundError(f"Skill source not found: {source_dir}")

    target_root.mkdir(parents=True, exist_ok=True)
    target_dir = target_root / skill_name

    if target_dir.exists():
        if not force:
            raise FileExistsError(
                f"Target already exists: {target_dir}. Rerun with --force to replace it safely."
            )
        backup_dir = target_root / f"{skill_name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.move(str(target_dir), str(backup_dir))
        print(f"Backed up existing skill to: {backup_dir}")

    shutil.copytree(source_dir, target_dir)
    return target_dir


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_dir).expanduser().resolve()
    target_root = Path(args.target_dir).expanduser().resolve()

    installed_dir = install_skill(
        source_root=source_root,
        target_root=target_root,
        skill_name=args.skill_name,
        force=args.force,
    )
    print(f"Installed skill to: {installed_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
