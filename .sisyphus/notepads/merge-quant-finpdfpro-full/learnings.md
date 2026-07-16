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
