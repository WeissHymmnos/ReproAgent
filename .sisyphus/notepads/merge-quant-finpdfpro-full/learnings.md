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
