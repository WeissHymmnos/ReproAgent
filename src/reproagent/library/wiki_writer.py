"""生成逐因子 Markdown wiki 页。"""

from __future__ import annotations

from reproagent.models.library import FactorLibraryEntry
from reproagent.persistence.paths import AppPaths


class WikiWriter:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def update(self, entries: list[FactorLibraryEntry] | None = None) -> None:
        """为每个因子生成 wiki/factors/<factor_name>.md。"""
        if entries is None:
            return
        self.paths.wiki_factors_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            self.write_entry(entry)

    def write_entry(self, entry: FactorLibraryEntry) -> None:
        """写入单个因子 wiki 页。"""
        self.paths.wiki_factors_dir.mkdir(parents=True, exist_ok=True)
        f = entry.factor
        lines = [
            f"# {f.name_cn} ({f.name})",
            "",
            f"- **风格**: {f.style}",
            f"- **版本**: {entry.version}",
            f"- **状态**: {entry.status}",
            f"- **Universe**: {f.universe}",
            f"- **调仓频率**: {f.rebalance_frequency}",
            f"- **去重哈希**: `{entry.dedup_hash}`",
            f"- **创建时间**: {entry.created_at:%Y-%m-%d %H:%M}",
            "",
            "## 公式",
            "",
            "```",
            f.formula,
            "```",
            "",
            "## 输入字段",
            "",
        ]
        for inp in f.input_fields:
            lines.append(f"- {inp}")
        lines.extend(
            [
                "",
                "## 标签",
                "",
                ", ".join(entry.tags) if entry.tags else "（无）",
                "",
                "[← 返回索引](../INDEX.md)",
                "",
            ]
        )
        out_path = self.paths.wiki_factors_dir / f"{f.name}.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")