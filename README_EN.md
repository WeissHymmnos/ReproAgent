# ReproAgent

Feed it a sell-side research report; it reproduces the factors inside.
PDF (or plain Markdown) goes in, factor definitions come out, get backtested
on your local data, then compared against the numbers the report claims.
If they disagree, it revises the formula by root cause and retries -- up to
three times -- before handing off to a human review queue. Factors that pass
land in a local library with wiki pages.

Targets China A-shares and convertible bonds. Single user, single machine:
SQLite plus Parquet files, no services to deploy.

## Try it

Python 3.12+ and [uv](https://docs.astral.sh/uv/).

    git clone <repo-url> && cd reproagent
    uv sync --extra dev

Offline smoke test, no API keys needed:

    OPENAI_API_KEY= ANTHROPIC_API_KEY= DATA_SOURCE=local \
      LOCAL_DATA_PATH=tests/fixtures/test_data \
      uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf

Two annotated benchmarks ship with the repo:

    DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
      uv run reproagent benchmark --run cb-factor-investing

Already have Markdown? Skip PDF parsing:

    uv run reproagent text -f report.md -b Huatai

Production: fill `LLM_API_KEY` in `.env`, set `APP_ENV=prod`. Strict mode --
no mock extraction, no silent formula fallback.

## What it does not do

Live trading. Portfolio optimization or risk models -- this covers single-factor
replication only. And it will not invent details a report never stated; missing
information routes to review instead.

## Commands

    reproagent ingest report.pdf      # validate + store
    reproagent reproduce report.pdf   # full pipeline
    reproagent text -f report.md      # markdown shortcut
    reproagent library [--html]       # browse factors
    reproagent review --list | --approve ID | --reject ID
    reproagent benchmark --list | --run ID | --run-all | --report
    reproagent serve                  # browser workbench on :8765
    reproagent tui                    # terminal UI
    reproagent mcp                    # MCP server for MCP-capable clients

`reproduce`/`text` emit one JSON document (`status`, `summary`, `factors`,
`data_context`). Watch for `soft_passed`: metrics did not match but the result
is healthy and registered -- count it separately from clean `passed`.

## Configuration

Environment variables or `.env`: `APP_ENV` (dev|prod), `LLM_API_KEY`,
`LLM_PROVIDER`/`LLM_MODEL` (openai or anthropic), `PARSER_BACKEND`,
`DATA_SOURCE` (`local`/`ricequant`/`qlib`/`tushare`), `LOCAL_DATA_PATH`.
Optional extras: instructor, ricequant, tushare, paddle, vlm, formula, mcp.

## Development

    make test    # or: OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
    make lint

If you touch the engine or pipeline, run `benchmark --run-all`; ground truth
catches most regressions. Start reading at `pipeline.py::reproduce_text`.

MIT license. 中文文档见 [README.md](README.md) 与 docs/user-manual/.
