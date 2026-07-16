# Learnings — merge-quant-finpdfpro-full

## 2026-07-17 Session start
- Plan: `.sisyphus/plans/merge-quant-finpdfpro-full.md` (30 tasks + F1-F4)
- Sources: finpdfpro at `/home/wh/Documents/finpdfpro`, zip at `/tmp/opencode/quant-agent-zip/量化agent/`
- Wave 0 is blocking: vendor → deps → settings → legacy → fixtures

## Task 1: Vendor finreportparser
- Successfully copied `finreportparser` source code excluding `__pycache__`, `*.pyc`, and `.mypy_cache`.
- Copied configs to both package-local (`src/finreportparser/configs/`) and repo root (`configs/`).
- Fixed `find_configs_dir()` in `src/finreportparser/config.py` to prioritize package-local configs, then src layout repo root, and finally cwd fallback.
- Checked for `numpy` version pins in the vendored code and found none.
- Verified that the package is importable and configs can be loaded successfully.

## Task 2: Update pyproject.toml deps + hatch packages + .env.example
- Added core dependencies to `pyproject.toml`: `pymupdf>=1.24.11`, `tqdm>=4.65.0`, `pillow>=10.0.0`, `httpx>=0.25.0`, `pandas>=2.0`.
- Updated `[tool.hatch.build.targets.wheel]` to include both `src/reproagent` and `src/finreportparser` in `packages` and `force-include`.
- Removed deprecated parser extras (`parser-marker`, `parser-llama`, `parser-mineru`) and added new optional extras: `ricequant`, `qlib`, `paddle`, `vlm`, `formula`.
- Updated `.env.example` with `PARSER_BACKEND=finpdfpro`, `FINPDFPRO_MODE=balanced`, `FINPDFPRO_VLM_BACKEND=none`, `DATA_SOURCE=local`, and other data backend variables.
- Successfully ran `uv sync --all-extras` and verified imports and config loading.

## Task 3: Extend Settings for finpdfpro and aiminer-like data backends
- Updated `Settings` in `src/reproagent/settings.py` to include `finpdfpro_mode`, `finpdfpro_vlm_backend`, `qlib_data_path`, `local_data_path`, `rq_user`, and `rq_pass`.
- Configured `ricequant_token`, `rq_user`, and `rq_pass` with `AliasChoices` to support both lowercase and uppercase environment variables (e.g., `RQ_USER`, `RQ_PASS`, `RQ_TOKEN`, `RICEQUANT_TOKEN`).
- Updated `LayoutExtractor` backend literal to support `"finpdfpro"` and default to it.
- Updated `ReplicationConfig` data_source literal to support `"qlib"` and default to `"local"`.
- Verified settings loading and environment variable mapping successfully.

## Task 5: Create test fixtures
- Generated a valid 2-page PDF fixture `tests/fixtures/sample_reports/minimal.pdf` containing Chinese and English text using PyMuPDF (fitz) with the `china-s` font.
- Generated a synthetic OHLCV parquet fixture `tests/fixtures/test_data/prices.parquet` using Polars, containing 30 trading days and 2 instruments (`000001.SZ`, `600000.SH`) with valid OHLCV values.
- Updated `tests/conftest.py` to define `sample_report_path` and `prices_parquet_path` fixtures pointing to the new files.
- Added unit tests in `tests/unit/test_fixtures.py` to verify the correctness of the generated fixtures.

## Task 4: Place quant agent zip into `src/reproagent/legacy_quant/`
- Created the package directory `src/reproagent/legacy_quant/` and wrote `__init__.py` exposing `FactorDB`, `FactorDiscoverer`, `DeviationController`, and `generate_dashboard`.
- Copied and adapted `factor_db.py`, `factor_research_pipeline.py`, and `factor_library_dashboard.py` from the zip file.
- Fixed all bare imports to package-relative imports (e.g., `from .factor_db import FactorDB`).
- Refactored `factor_library_dashboard.py` to wrap the HTML generation logic in a `generate_dashboard(db_path, output_path)` function so that importing the module does not automatically write the HTML file.
- Created `__main__.py` to allow running the package as a module (`python -m reproagent.legacy_quant`) which seeds demo data to `/tmp/legacy_factor.db` and generates the HTML dashboard to `/tmp/factor_library.html`.
- Cleaned up the virtual environment's site-packages to ensure the editable install of `reproagent` is correctly resolved from the `src/` directory.
- Verified the package imports and functionality using the specified verification commands, and saved the outputs to `.sisyphus/evidence/task-4-legacy-import.txt` and `.sisyphus/evidence/task-4-seed.txt`.

## Task 9: Implement plotting utilities
- Implemented `save_equity_curve_chart`, `save_group_returns_chart`, and `save_ic_timeseries_chart` in `src/reproagent/utils/plotting.py`.
- Configured matplotlib to use the non-interactive `'Agg'` backend before importing `pyplot` to prevent GUI-related errors in headless environments.
- Handled various input data formats (lists, dicts, pandas Series) robustly.
- Ensured parent directories are created automatically and figures are closed properly to prevent memory leaks.

## Task 8: Implement CacheManager in `src/reproagent/cache/cache_manager.py`
- Implemented `CacheManager` to manage filesystem cache under `paths.cache_entry_dir(cache_key)/`.
- Handled serialization and deserialization of `ParsedFactorSpec` lists, `ReplicationConfig`, and `BacktestResult` using Pydantic v2 `model_dump`, `model_validate`, `model_dump_json`, and `model_validate_json`.
- Implemented `get_cached_backtest` to support both single `backtest.json` matching the requested `factor_id` and keyed `backtest_{factor_id}.json` files.
- Ensured directories are created automatically on `save`.
- Verified the implementation with a comprehensive roundtrip test script and ensured `lsp_diagnostics` is completely clean.

## Task 10 — ingestion (uploader / validator / review_queue)
- `upload_pdf` resolves path, raises `FileNotFoundError` (not exists) / `ValidationError` (not a file) — matches `utils/pdf.py` precedent. Uses `datetime.now(UTC)` (not deprecated `utcnow()`).
- `validate_pdf` returns a NEW report via `model_copy(update=...)` (Pydantic v2 immutable update) — never mutates the input. Per masterplan §子系统1: page_count > 200 → warning appended to `validation_errors` but status stays `valid` ("告警不阻断"). Implemented `_only_warning` helper to distinguish pure-warning case from hard errors.
- `review_queue` accepts optional `Repository` injection; falls back to `_default_repo()` which builds engine from `get_settings().db_path` + `init_db`. This makes functions usable both standalone (CLI default DB) and testable with injected in-memory/temp engine.
- `enqueue_manual_review` calls `repo.save_report(report)` before `enqueue_review` — upsert semantics handle both fresh and already-persisted reports (Repository.save_report checks existing row).
- `confirm_manual_review` maps `approve`→`approved` / `reject`→`rejected` (Repository stores status as free string; table comment says "pending / approved / rejected").
- `dequeue_review` in Repository does NOT mutate status (peek-only) — confirmed by test: after approve, `dequeue_manual_review` returns None because `update_review_status` moved it out of `pending`. Good: dequeue is non-destructive, confirm is destructive.
- Implemented schema_validator.py to validate factor specs and append warnings for low extraction confidence.
- Implemented config_builder.py to assemble ReplicationConfig and export it as config.yaml.
- Implemented report_parser.py to orchestrate LayoutExtractor, LLMExtractor, SchemaValidator, and ConfigBuilder.

## Tasks 20-22 (deviation + library + dashboard)

### Task 20: DeviationAnalyzer + root_cause
- BacktestResult fields: ic_mean, ic_ir, long_short_annual_return, sharpe_ratio, max_drawdown
- ReportedMetrics fields: ic_mean, ic_ir, long_short_return, sharpe_ratio, max_drawdown (all Optional, None = skip)
- ToleranceConfig: ic_mean_abs, ic_ir_abs, long_short_return_rel, sharpe_abs, max_drawdown_abs
- DeviationReport.metric_deviations keys: ic_mean, ic_ir, long_short_annual_return, sharpe_ratio, max_drawdown
- should_reflect: False if passed, False if status != in_progress, True if current_iteration < max_iterations
- root_cause classify: heuristic on metric_deviations deltas (signs, magnitudes)

### Task 21: Library manager
- Repository has save_library_entry, get_library_entry, list_library_entries, get_by_dedup_hash
- SQLModel metadata.create_all(engine) to init tables (no init_db helper)
- FactorLibraryTable has FK report_id -> reports.id, so must save_report first
- register flow: compute_dedup_hash -> dedup_check -> bump patch if exists (reuse id) -> classify -> save -> update_index/wiki
- StyleClassifier: rule keywords lowercased match against name+name_cn+formula
- IndexWriter writes wiki/INDEX.md; WikiWriter writes wiki/factors/<name>.md

### Task 22: HTML dashboard
- Ported Chart.js dark HTML from legacy_quant/factor_library_dashboard.py
- generate_html_dashboard(factors: list[dict], output_path) -> Path (no SQLite dep)
- Added per-file-ignores E501 in pyproject.toml for dashboard.py (HTML template lines)
- Export from library/__init__.py
