import io
import logging
from typing import Any

from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider

logger = logging.getLogger(__name__)

class SmolVlmProvider(BaseVLMProvider):
    def __init__(self, model_client: Any | None = None):
        self.model_client = model_client
        self._model = None
        self._processor = None
        self._init_failed = False

    def _lazy_init(self) -> bool:
        if self.model_client is not None:
            return True
        if self._model is not None and self._processor is not None:
            return True
        if self._init_failed:
            return False

        try:
            import torch
            from transformers import AutoModelForVision2Seq, AutoProcessor

            model_id = "HuggingFaceTB/SmolVLM-256M-Instruct"
            self._processor = AutoProcessor.from_pretrained(model_id)

            dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32

            self._model = AutoModelForVision2Seq.from_pretrained(
                model_id,
                torch_dtype=dtype,
                _fast_init=False,
            )

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = self._model.to(device)

            return True
        except ImportError:
            logger.warning("transformers or torch not installed. SmolVLM backend unavailable.")
            self._init_failed = True
            return False
        except Exception as e:
            logger.warning(f"Failed to load SmolVLM model: {e}")
            self._init_failed = True
            return False

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        if self.model_client is not None:
            if hasattr(self.model_client, "describe_chart"):
                return self.model_client.describe_chart(image_bytes)
            return ChartMeta(
                chart_type="unknown",
                title="SmolVLM Chart",
                description="Chart described by SmolVLM.",
                data_points=[]
            )

        if not self._lazy_init():
            return ChartMeta(
                chart_type="unknown",
                title="Unknown Chart",
                description="SmolVLM backend unavailable. Chart description not available.",
                data_points=[]
            )

        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            prompt = (
                "Describe this chart in detail. What type of chart is it, "
                "what is the title, and what are the key data points or trends?"
            )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]

            text = self._processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = self._processor(text=text, images=[image], return_tensors="pt")

            device = self._model.device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            generated_ids = self._model.generate(**inputs, max_new_tokens=500)
            generated_texts = self._processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )

            description = generated_texts[0]

            chart_type = "unknown"
            if "bar" in description.lower():
                chart_type = "bar"
            elif "line" in description.lower():
                chart_type = "line"
            elif "pie" in description.lower():
                chart_type = "pie"

            return ChartMeta(
                chart_type=chart_type,
                title="SmolVLM Chart",
                description=description.strip(),
                data_points=[]
            )

        except Exception as e:
            logger.error(f"Error describing chart with SmolVLM: {e}")
            return ChartMeta(
                chart_type="unknown",
                title="Error",
                description=f"Failed to describe chart: {e}",
                data_points=[]
            )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        if self.model_client is not None:
            if hasattr(self.model_client, "diagram_to_mermaid_candidates"):
                return self.model_client.diagram_to_mermaid_candidates(image_bytes)
            return []

        if not self._lazy_init():
            return []

        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            prompt = "Convert this diagram to a Mermaid.js graph. Output only the Mermaid code block."

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]

            text = self._processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = self._processor(text=text, images=[image], return_tensors="pt")

            device = self._model.device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            generated_ids = self._model.generate(**inputs, max_new_tokens=500)
            generated_texts = self._processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )

            description = generated_texts[0]

            if "```mermaid" in description:
                parts = description.split("```mermaid")
                if len(parts) > 1:
                    code = parts[1].split("```")[0].strip()
                    return [code]
            elif "```" in description:
                parts = description.split("```")
                if len(parts) > 1:
                    code = parts[1].strip()
                    if code.startswith("graph") or code.startswith("flowchart") or code.startswith("pie"):
                        return [code]

            return [description.strip()]

        except Exception as e:
            logger.error(f"Error converting diagram to mermaid with SmolVLM: {e}")
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
