"""SmolVLM-256M edge vision-language backend.

Primary role in classify-first pipeline: **chart type classification**.
Description can still be generated, but fusion with OCR is preferred via EdgeHybridVLM.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any

from finreportparser.types import ChartClassification, ChartMeta, ChartType
from finreportparser.vlm.chart_classify import CLASSIFY_PROMPT, parse_vlm_label

logger = logging.getLogger(__name__)

# Small edge-friendly default; override with FINREPORTPARSER_EDGE_VLM_MODEL
DEFAULT_MODEL_ID = os.environ.get(
    "FINREPORTPARSER_EDGE_VLM_MODEL",
    "HuggingFaceTB/SmolVLM-256M-Instruct",
)


class SmolVlmProvider:
    def __init__(self, model_client: Any | None = None, model_id: str | None = None):
        self.model_client = model_client
        self.model_id = model_id or DEFAULT_MODEL_ID
        self._model = None
        self._processor = None
        self._init_failed = False
        self._device = "cpu"

    def _lazy_init(self) -> bool:
        if self.model_client is not None:
            return True
        if self._model is not None and self._processor is not None:
            return True
        if self._init_failed:
            return False

        try:
            import torch
            from transformers import AutoProcessor

            # transformers ≥5: Vision2Seq renamed; prefer SmolVLM / ImageTextToText
            try:
                from transformers import AutoModelForImageTextToText as _AutoVLM
            except ImportError:  # pragma: no cover
                try:
                    from transformers import AutoModelForVision2Seq as _AutoVLM
                except ImportError:
                    from transformers import SmolVLMForConditionalGeneration as _AutoVLM

            logger.info("Loading edge VLM: %s", self.model_id)
            self._processor = AutoProcessor.from_pretrained(self.model_id)

            use_cuda = torch.cuda.is_available()
            use_mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            if use_cuda and torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
            elif use_cuda:
                dtype = torch.float16
            else:
                dtype = torch.float32

            # transformers 5 prefers `dtype=` over deprecated `torch_dtype=`
            try:
                self._model = _AutoVLM.from_pretrained(self.model_id, dtype=dtype)
            except TypeError:
                try:
                    self._model = _AutoVLM.from_pretrained(
                        self.model_id, torch_dtype=dtype
                    )
                except TypeError:
                    self._model = _AutoVLM.from_pretrained(self.model_id)

            if use_cuda:
                self._device = "cuda"
            elif use_mps:
                # MPS can be fragile for some VLM ops; still prefer when available
                self._device = "mps"
            else:
                self._device = "cpu"
            self._model = self._model.to(self._device)
            self._model.eval()
            return True
        except ImportError:
            logger.warning(
                "transformers/torch not installed. Edge VLM unavailable "
                "(uv sync --extra vlm)."
            )
            self._init_failed = True
            return False
        except Exception as e:
            logger.warning("Failed to load edge VLM %s: %s", self.model_id, e)
            self._init_failed = True
            return False

    def _generate(self, image_bytes: bytes, prompt: str, max_new_tokens: int = 64) -> str | None:
        if self.model_client is not None and hasattr(self.model_client, "generate"):
            return self.model_client.generate(image_bytes, prompt)

        if not self._lazy_init():
            return None

        try:
            import torch
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            # Keep edge footprint small
            max_side = 768
            w, h = image.size
            scale = min(1.0, max_side / max(w, h))
            if scale < 1.0:
                image = image.resize((int(w * scale), int(h * scale)))

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = self._processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = self._processor(text=text, images=[image], return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.inference_mode():
                generated_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )
            # Decode only the newly generated tokens when possible
            in_len = inputs["input_ids"].shape[-1]
            new_tokens = generated_ids[:, in_len:]
            out = self._processor.batch_decode(new_tokens, skip_special_tokens=True)
            if out and out[0].strip():
                return out[0].strip()
            # Fallback full decode
            full = self._processor.batch_decode(generated_ids, skip_special_tokens=True)
            return (full[0] if full else "").strip()
        except Exception as e:
            logger.error("Edge VLM generate failed: %s", e)
            return None

    def classify_chart(self, image_bytes: bytes) -> ChartClassification | None:
        """Visual-only classification with constrained label set."""
        if self.model_client is not None and hasattr(self.model_client, "classify_chart"):
            return self.model_client.classify_chart(image_bytes)

        raw = self._generate(image_bytes, CLASSIFY_PROMPT, max_new_tokens=16)
        if raw is None:
            return ChartClassification(
                chart_type=ChartType.UNKNOWN,
                confidence=0.0,
                source="vlm",
                rationale="edge_vlm_unavailable",
            )

        ctype, conf = parse_vlm_label(raw)
        return ChartClassification(
            chart_type=ctype,
            confidence=conf,
            source="vlm",
            vlm_type=ctype,
            vlm_confidence=conf,
            rationale=f"raw={raw[:80]!r}",
            labels_considered=[t.value for t in ChartType if t != ChartType.UNKNOWN],
        )

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        if self.model_client is not None:
            if hasattr(self.model_client, "describe_chart"):
                return self.model_client.describe_chart(image_bytes)
            return ChartMeta(
                chart_type="unknown",
                title="SmolVLM Chart",
                description="Chart described by SmolVLM.",
                data_points=[],
            )

        # Classify first, then free-form describe
        cls = self.classify_chart(image_bytes)
        chart_type = cls.chart_type.value if cls else "unknown"

        prompt = (
            f"This image was classified as: {chart_type}. "
            "Describe the chart/diagram in detail: title, axes or panels, "
            "key labels, and main takeaways. Be concise."
        )
        description = self._generate(image_bytes, prompt, max_new_tokens=256)
        if description is None:
            return ChartMeta(
                chart_type=chart_type,
                title="Unknown Chart",
                description="SmolVLM backend unavailable. Chart description not available.",
                data_points=[],
                classification=cls,
            )

        return ChartMeta(
            chart_type=chart_type,
            title="SmolVLM Chart",
            description=description.strip(),
            data_points=[],
            classification=cls,
        )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        if self.model_client is not None:
            if hasattr(self.model_client, "diagram_to_mermaid_candidates"):
                return self.model_client.diagram_to_mermaid_candidates(image_bytes)
            return []

        prompt = (
            "Convert this diagram to a Mermaid.js flowchart. "
            "Output only the Mermaid code starting with graph or flowchart."
        )
        description = self._generate(image_bytes, prompt, max_new_tokens=400)
        if not description:
            return []

        if "```mermaid" in description:
            parts = description.split("```mermaid")
            if len(parts) > 1:
                code = parts[1].split("```")[0].strip()
                return [code]
        if "```" in description:
            parts = description.split("```")
            if len(parts) > 1:
                code = parts[1].strip()
                if code.startswith(("graph", "flowchart", "pie")):
                    return [code]
        stripped = description.strip()
        if stripped.startswith(("graph", "flowchart")):
            return [stripped]
        return []

    def unload(self) -> None:
        if self.model_client and hasattr(self.model_client, "unload"):
            self.model_client.unload()
        self.model_client = None

        if self._model is not None:
            try:
                import torch

                del self._model
                self._model = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

        self._processor = None
