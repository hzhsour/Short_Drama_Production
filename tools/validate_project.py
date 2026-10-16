#!/usr/bin/env python3
"""Validate the short-drama project scaffold and storyboard JSON files."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.validation import validate_project  # noqa: E402


def main() -> int:
    errors = validate_project(ROOT)
    if errors:
        print("项目检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("项目目录、Codex Skills 和分镜 JSON 检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
