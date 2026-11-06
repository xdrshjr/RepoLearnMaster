"""导出/校验前后端契约（spec §4.1 / §5.7）。

用法：
    python scripts/export_contracts.py            # 导出
    python scripts/export_contracts.py --check    # 只校验漂移（CI 用）

它与 `python -m repolearn.cli export-openapi` 做同一件事，保留独立脚本是为了让
"没装项目（没跑过 pip install -e .）的人"也能在 CI 里调用——用 `PYTHONPATH`
兜底即可，不需要先把包装好。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 RepoLearn 的 OpenAPI 契约")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    from repolearn.main import create_app

    spec = create_app().openapi()
    target = ROOT / "packages" / "contracts" / "openapi.json"
    body = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not target.is_file():
            print(f"missing {target}", file=sys.stderr)
            return 1
        if target.read_text(encoding="utf-8") != body:
            print(
                "contract drift: openapi.json 与代码不一致。\n"
                "运行 `python scripts/export_contracts.py` 重新导出，并与代码改动一起提交。",
                file=sys.stderr,
            )
            return 1
        print("contract up to date")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({len(spec.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
