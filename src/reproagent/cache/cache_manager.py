"""CacheManager：命中/未命中与落盘。"""

from __future__ import annotations

import json
from pathlib import Path

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.persistence.paths import AppPaths


class CacheManager:
    """文件系统缓存：~/.reproagent/cache/<cache_key>/。"""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def get_cached(
        self, cache_key: str
    ) -> tuple[str, list[ParsedFactorSpec], ReplicationConfig] | None:
        """命中 → (markdown, specs, config)；未命中 → None。"""
        entry_dir = self.paths.cache_entry_dir(cache_key)
        markdown_path = entry_dir / "markdown.md"
        specs_path = entry_dir / "specs.json"
        config_path = entry_dir / "config.json"

        if not (markdown_path.exists() and specs_path.exists() and config_path.exists()):
            return None

        try:
            with open(markdown_path, encoding="utf-8") as f:
                markdown = f.read()

            with open(specs_path, encoding="utf-8") as f:
                specs_data = json.load(f)
            specs = [ParsedFactorSpec.model_validate(item) for item in specs_data]

            with open(config_path, encoding="utf-8") as f:
                config = ReplicationConfig.model_validate_json(f.read())

            return markdown, specs, config
        except Exception:
            return None

    def get_cached_backtest(
        self,
        cache_key: str,
        factor_id: str,
        params_token: str | None = None,
    ) -> BacktestResult | None:
        """命中 → 缓存回测结果；否则 None。"""
        entry_dir = self.paths.cache_entry_dir(cache_key)
        names: list[str] = []
        if params_token:
            names.append(f"backtest_{factor_id}_{params_token}.json")
        else:
            names.append(f"backtest_{factor_id}.json")
            names.append("backtest.json")

        for name in names:
            path = entry_dir / name
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    res = BacktestResult.model_validate_json(f.read())
                if name == "backtest.json" and res.factor_id != factor_id:
                    continue
                return res
            except Exception:
                continue

        return None

    def save(
        self,
        cache_key: str,
        markdown: str,
        specs: list[ParsedFactorSpec],
        config: ReplicationConfig,
        backtest_result: BacktestResult | None = None,
        params_token: str | None = None,
    ) -> None:
        """保存缓存到 cache/<cache_key>/。"""
        entry_dir = self.paths.cache_entry_dir(cache_key)
        entry_dir.mkdir(parents=True, exist_ok=True)

        markdown_path = entry_dir / "markdown.md"
        specs_path = entry_dir / "specs.json"
        config_path = entry_dir / "config.json"

        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        specs_data = [spec.model_dump(mode="json") for spec in specs]
        with open(specs_path, "w", encoding="utf-8") as f:
            json.dump(specs_data, f, ensure_ascii=False, indent=2)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config.model_dump_json(indent=2))

        if backtest_result is not None:
            payload = backtest_result.model_dump_json(indent=2)
            if params_token:
                token_path = (
                    entry_dir / f"backtest_{backtest_result.factor_id}_{params_token}.json"
                )
                token_path.write_text(payload, encoding="utf-8")
            backtest_path = entry_dir / "backtest.json"
            backtest_path.write_text(payload, encoding="utf-8")
            factor_backtest_path = entry_dir / f"backtest_{backtest_result.factor_id}.json"
            factor_backtest_path.write_text(payload, encoding="utf-8")

    def cache_dir(self, cache_key: str) -> Path:
        return self.paths.cache_entry_dir(cache_key)
