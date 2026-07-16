# Decisions — merge-quant-finpdfpro-full

- Vendor finreportparser into `src/finreportparser` (sibling package)
- legacy_quant: as-is side module, relative imports only
- Data backends: ricequant | qlib | local (aiminer pattern)
- LLM: real + mock fallback when no key
- Full TUI + HTML dashboard
- Tests: tests-after + agent QA
