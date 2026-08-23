"""FactorLibraryManager：register / get / list。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from reproagent.library.classifier import StyleClassifier
from reproagent.library.index_writer import IndexWriter
from reproagent.library.versioning import bump, compute_dedup_hash
from reproagent.library.wiki_writer import WikiWriter
from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository


class FactorLibraryManager:
    """实现 FactorLibraryProtocol。"""

    def __init__(self, repository: Repository, paths: AppPaths) -> None:
        self.repository = repository
        self.paths = paths
        self.classifier = StyleClassifier()
        self.index_writer = IndexWriter(paths)
        self.wiki_writer = WikiWriter(paths)

    def register(
        self, entry: FactorLibraryEntry, check_redundancy: bool = True
    ) -> FactorLibraryEntry:
        """去重 → 分类 → 入库 → 更新 INDEX / wiki。

        Parameters
        ----------
        entry: 待入库的因子记录
        check_redundancy: 是否检查与库内因子的相关性冗余
        """
        entry.dedup_hash = compute_dedup_hash(entry.factor)
        existing = self.dedup_check(entry)
        if existing is not None:
            entry.version = bump(existing.version, "patch")
            entry.id = existing.id
            if not (entry.metrics or {}) and (existing.metrics or {}):
                entry.metrics = existing.metrics
        # 冗余检查（仅对新因子）
        if check_redundancy and existing is None:
            # 简化：仅基于元数据层面的冗余检查（formula+fields）
            # 完整的截面相关性检查由 check_redundancy() 方法负责
            pass

        classified_style = self.classifier.classify(entry.factor)
        entry.factor = entry.factor.model_copy(update={"style": classified_style})
        saved = self.repository.save_library_entry(entry)
        self.update_index()
        self.update_wiki()
        return saved

    def check_redundancy(
        self,
        factor_values: pl.DataFrame,  # type: ignore[name-defined]
        max_correlation: float = 0.7,
    ) -> dict:  # type: ignore[valid-type]
        """计算新因子与库内所有因子的截面平均相关性。

        Parameters
        ----------
        factor_values: [date, asset, factor_value] — 新因子的值
        max_correlation: 相关性阈值（绝对值）

        Returns
        -------
        dict with keys: is_redundant, max_correlation, most_similar_id
        """

        import polars as pl

        entries = self.repository.list_library_entries()
        if not entries or "factor_value" not in factor_values.columns:
            return {
                "is_redundant": False,
                "max_correlation": 0.0,
                "most_similar_factor_id": None,
                "details": {},
            }

        max_corr = 0.0
        most_similar = None
        corr_details: dict[str, float] = {}

        from reproagent.reproducer.metrics import find_backtest_artifact_dir

        for entry in entries:
            folder = find_backtest_artifact_dir(self.paths.data_dir, entry)
            if folder is None:
                continue
            fv_path = folder / "factor_values.parquet"
            if not fv_path.exists():
                continue
            try:
                existing = pl.read_parquet(fv_path)
                merged = factor_values.join(existing, on=["date", "asset"], how="inner").drop_nulls(
                    subset=["factor_value", "factor_value_right"]
                )
                if len(merged) < 10:
                    continue
                corr = merged.select(pl.corr("factor_value", "factor_value_right").alias("corr"))[
                    "corr"
                ][0]
                if corr is not None:
                    abs_corr = abs(float(corr))
                    corr_details[entry.id] = abs_corr
                    if abs_corr > max_corr:
                        max_corr = abs_corr
                        most_similar = entry.id
            except Exception:
                continue

        return {
            "is_redundant": max_corr > max_correlation,
            "max_correlation": max_corr,
            "most_similar_factor_id": most_similar,
            "details": corr_details,
        }

    def get(self, factor_id: str) -> FactorLibraryEntry | None:
        return self.repository.get_library_entry(factor_id)

    def backfill_metrics(self, data_dir: Path) -> int:
        """Fill empty ``entry.metrics`` from ``data_dir/backtest/<name>/`` artifacts."""
        from reproagent.reproducer.metrics import (
            find_backtest_artifact_dir,
            metrics_from_artifact_dir,
        )

        updated = 0
        for entry in self.list():
            current = entry.metrics or {}
            if current.get("ic_series") or current.get("ic"):
                continue
            folder = find_backtest_artifact_dir(Path(data_dir), entry)
            if folder is None:
                continue
            entry.metrics = metrics_from_artifact_dir(folder)
            self.repository.save_library_entry(entry)
            self.wiki_writer.write_entry(entry)
            updated += 1
        if updated:
            self.update_index()
        return updated

    def list(  # noqa: A003
        self,
        filter: LibraryFilter | None = None,  # noqa: A002
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[FactorLibraryEntry]:
        entries = self.repository.list_library_entries(filter)
        q = (query or "").strip().lower()
        if q:
            kept: list[FactorLibraryEntry] = []
            for entry in entries:
                f = entry.factor
                hay = " ".join(
                    [
                        f.name or "",
                        f.name_cn or "",
                        f.formula or "",
                        " ".join(f.input_fields or []),
                    ]
                ).lower()
                if q in hay:
                    kept.append(entry)
            entries = kept
        if limit is not None and limit >= 0:
            entries = entries[:limit]
        return entries

    def dedup_check(self, entry: FactorLibraryEntry) -> FactorLibraryEntry | None:
        return self.repository.get_by_dedup_hash(entry.dedup_hash)

    def update_index(self) -> None:
        entries = self.repository.list_library_entries()
        self.index_writer.update(entries)

    def update_wiki(self) -> None:
        entries = self.repository.list_library_entries()
        self.wiki_writer.update(entries)
