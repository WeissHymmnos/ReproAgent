"""跨报告经验记忆：实现 Ralph Loop (retrieve-generate-evaluate-distill)。

在每次复现（成功或失败）后记录因子模式、术语映射和失败根因，
在新研报提取时查询相似历史模式，注入反思 prompt 中。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel


class SuccessfulPattern(BaseModel):
    """成功的因子模式。"""

    key: str  # 唯一标识 = hash(formula_template + input_fields)
    formula_template: str  # 参数化模版, e.g. "close/Ref(close,N)-1"
    style: str
    input_fields: list[str]
    avg_ic: float
    n_successes: int = 1
    report_ids: list[str]
    created_at: datetime
    updated_at: datetime


class FailedPattern(BaseModel):
    """失败的因子模式。"""

    key: str
    formula_template: str
    failure_mode: str  # RootCause 值
    deviation_signature: str  # 归一化指标偏差
    n_failures: int = 1
    report_ids: list[str]
    created_at: datetime
    updated_at: datetime


class TermMapping(BaseModel):
    """研报术语 → 规范化术语 映射。"""

    report_term: str
    canonical_term: str
    confidence: float  # 0–1
    n_occurrences: int = 1
    last_seen_at: datetime


class ExperienceMemory:
    """基于 SQLModel + SQLite 的经验记忆存储。

    直接在内存字典中操作（对个人使用的数量级完全足够），
    可选持久化到 SQLite 表。
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._successes: dict[str, SuccessfulPattern] = {}
        self._failures: dict[str, FailedPattern] = {}
        self._term_mappings: dict[str, TermMapping] = {}
        self._db_path = db_path

    @staticmethod
    def _extract_template(formula: str) -> str:
        """从公式中提取参数化模版。"""
        # 将数字替换为 N
        tpl = re.sub(r"\b\d+\b", "N", formula)
        # 归一化空格
        tpl = re.sub(r"\s+", "", tpl)
        return tpl

    @staticmethod
    def _make_key(formula: str, input_fields: list[str]) -> str:
        import hashlib

        template = ExperienceMemory._extract_template(formula)
        payload = f"{template}|{','.join(sorted(input_fields))}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def record_success(
        self,
        formula: str,
        input_fields: list[str],
        style: str,
        ic: float,
        report_id: str,
        n_successes: int = 1,
    ) -> SuccessfulPattern:
        key = self._make_key(formula, input_fields)
        now = datetime.now(UTC)
        if key in self._successes:
            existing = self._successes[key]
            total = existing.n_successes + n_successes
            existing.avg_ic = (existing.avg_ic * existing.n_successes + ic * n_successes) / total
            existing.n_successes = total
            if report_id not in existing.report_ids:
                existing.report_ids.append(report_id)
            existing.updated_at = now
            return existing

        pattern = SuccessfulPattern(
            key=key,
            formula_template=self._extract_template(formula),
            style=style,
            input_fields=input_fields,
            avg_ic=ic,
            n_successes=n_successes,
            report_ids=[report_id],
            created_at=now,
            updated_at=now,
        )
        self._successes[key] = pattern
        return pattern

    def record_failure(
        self,
        formula: str,
        input_fields: list[str],
        failure_mode: str,
        deviation_values: dict[str, float],
        report_id: str,
    ) -> FailedPattern:
        key = self._make_key(formula, input_fields)
        now = datetime.now(UTC)
        sig = ",".join(f"{k}:{v:.3f}" for k, v in sorted(deviation_values.items()))

        if key in self._failures:
            existing = self._failures[key]
            existing.n_failures += 1
            existing.deviation_signature = sig
            if report_id not in existing.report_ids:
                existing.report_ids.append(report_id)
            existing.updated_at = now
            return existing

        pattern = FailedPattern(
            key=key,
            formula_template=self._extract_template(formula),
            failure_mode=failure_mode,
            deviation_signature=sig,
            report_ids=[report_id],
            created_at=now,
            updated_at=now,
        )
        self._failures[key] = pattern
        return pattern

    def query_similar(
        self,
        formula: str,
        input_fields: list[str],
        top_k: int = 5,
    ) -> dict[str, list]:
        """查询与给定公式/字段相似的历史成功和失败记录。

        使用模糊匹配（模版子串 + 字段 overlap）。
        """
        tpl = self._extract_template(formula)
        fields = set(input_fields)

        # 相似成功记录
        similar_successes: list[tuple[float, SuccessfulPattern]] = []
        for s in self._successes.values():
            score = self._similarity(tpl, fields, s.formula_template, set(s.input_fields))
            if score > 0:
                similar_successes.append((score, s))

        similar_successes.sort(key=lambda x: x[0], reverse=True)

        # 相似失败记录
        similar_failures: list[tuple[float, FailedPattern]] = []
        for f in self._failures.values():
            score = self._similarity(tpl, fields, f.formula_template, set())
            if score > 0:
                similar_failures.append((score, f))

        similar_failures.sort(key=lambda x: x[0], reverse=True)

        return {
            "successes": [s for _, s in similar_successes[:top_k]],
            "failures": [f for _, f in similar_failures[:top_k]],
        }

    @staticmethod
    def _similarity(
        tpl_a: str,
        fields_a: set[str],
        tpl_b: str,
        fields_b: set[str],
    ) -> float:
        """0-1 相似度分数。"""
        field_overlap = len(fields_a & fields_b) / max(len(fields_a | fields_b), 1)
        # 简单的子串匹配
        tpl_score = 0.0
        if tpl_a == tpl_b:
            tpl_score = 1.0
        elif tpl_a in tpl_b or tpl_b in tpl_a:
            tpl_score = 0.7
        return 0.6 * tpl_score + 0.4 * field_overlap

    def get_category_stats(self, style: str | None = None) -> dict:
        """按风格返回成功/失败统计。"""
        successes = [s for s in self._successes.values() if style is None or s.style == style]
        failures = [f for f in self._failures.values() if style is None]
        return {
            "n_successes": len(successes),
            "n_failures": len(failures),
            "avg_ic": (sum(s.avg_ic for s in successes) / len(successes) if successes else 0.0),
            "top_formulas": [
                s.formula_template
                for s in sorted(successes, key=lambda x: x.avg_ic, reverse=True)[:5]
            ],
        }

    def learn_term_mapping(
        self,
        report_term: str,
        canonical_term: str,
        confidence: float,
    ) -> TermMapping:
        key = report_term.lower()
        now = datetime.now(UTC)
        if key in self._term_mappings:
            existing = self._term_mappings[key]
            existing.n_occurrences += 1
            existing.confidence = max(existing.confidence, confidence)
            existing.last_seen_at = now
            return existing
        mapping = TermMapping(
            report_term=report_term,
            canonical_term=canonical_term,
            confidence=confidence,
            last_seen_at=now,
        )
        self._term_mappings[key] = mapping
        return mapping

    def get_term_mapping(self, report_term: str) -> TermMapping | None:
        return self._term_mappings.get(report_term.lower())

    def build_reflection_context(self, formula: str, input_fields: list[str]) -> str:
        """构建注入反思 prompt 的经验上下文文本。"""
        similar = self.query_similar(formula, input_fields)
        parts: list[str] = []

        if similar["successes"]:
            parts.append("## 历史成功记录（相似公式模版）")
            for s in similar["successes"]:
                if isinstance(s, SuccessfulPattern):
                    parts.append(
                        f"- 模版: `{s.formula_template}` | "
                        f"风格: {s.style} | "
                        f"平均 IC: {s.avg_ic:.4f} | "
                        f"成功 {s.n_successes} 次"
                    )

        if similar["failures"]:
            parts.append("## 历史失败记录（相似公式模版，注意规避）")
            for f in similar["failures"]:
                if isinstance(f, FailedPattern):
                    parts.append(
                        f"- 模版: `{f.formula_template}` | "
                        f"失败模式: {f.failure_mode} | "
                        f"失败 {f.n_failures} 次"
                    )

        return "\n".join(parts)
