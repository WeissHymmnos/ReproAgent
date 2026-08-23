"""重生成全局 INDEX.md。"""

from __future__ import annotations

from reproagent.library.wiki_writer import safe_factor_filename
from reproagent.models.library import FactorLibraryEntry
from reproagent.persistence.paths import AppPaths


class IndexWriter:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def update(self, entries: list[FactorLibraryEntry] | None = None) -> None:
        """重生成 wiki/INDEX.md 表格（按 created_at 倒序）。"""
        if entries is None:
            return
        self.paths.wiki_dir.mkdir(parents=True, exist_ok=True)
        sorted_entries = sorted(entries, key=lambda e: e.created_at, reverse=True)
        lines = [
            "# 因子库索引",
            "",
            f"共 {len(sorted_entries)} 个因子。",
            "",
            "| 因子 | 风格 | IC | 版本 | 状态 | 去重哈希 | 创建时间 |",
            "|------|------|----|------|------|----------|----------|",
        ]
        for e in sorted_entries:
            metrics = getattr(e, "metrics", None) or {}
            ic = metrics.get("ic")
            ic_s = f"{float(ic):.3f}" if isinstance(ic, (int, float)) else "—"
            lines.append(
                f"| [{e.factor.name_cn}](factors/{safe_factor_filename(e.factor.name)}.md) "
                f"| {e.factor.style} | {ic_s} | {e.version} | {e.status} "
                f"| {e.dedup_hash[:8]} | {e.created_at:%Y-%m-%d %H:%M} |"
            )
        lines.append("")
        self.paths.wiki_index.write_text("\n".join(lines), encoding="utf-8")
