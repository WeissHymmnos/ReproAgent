import base64
import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider

logger = logging.getLogger(__name__)

def sanitize_text(text: str) -> str:
    text = re.sub(r'[\u0250-\u02AF]', '', text)
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    return text

class LlamaCppHttpProvider(BaseVLMProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:8080"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=60.0, trust_env=False)

    def _call_api(self, image_bytes: bytes, prompt: str, schema: dict[str, Any] | None = None) -> str:
        b64_img = base64.b64encode(image_bytes).decode('utf-8')

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            "temperature": 0.1,
        }

        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": schema
                }
            }

        try:
            response = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 500:
                logger.warning("HTTP 500 from VLM, retrying with sanitized prompt")
                sanitized_prompt = sanitize_text(prompt)
                payload["messages"][0]["content"][1]["text"] = sanitized_prompt
                try:
                    response = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e2:
                    logger.error(f"Retry failed: {e2}")
                    raise
            raise

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        schema = {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "data_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True
                    }
                }
            },
            "required": ["chart_type", "title", "description"]
        }

        prompt = (
            "Describe this chart in detail. Extract the title, chart type, "
            "and a comprehensive description of the trends and data shown."
        )

        try:
            result_str = self._call_api(image_bytes, prompt, schema)
            result_json = json.loads(result_str)
            return ChartMeta(**result_json)
        except (Exception, ValidationError) as e:
            logger.error(f"Failed to describe chart: {e}")
            return None

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        prompt = "Convert this diagram into Mermaid flowchart syntax. Return ONLY the Mermaid code block."
        try:
            result_str = self._call_api(image_bytes, prompt)
            match = re.search(r'```mermaid\n(.*?)\n```', result_str, re.DOTALL)
            if match:
                return [match.group(1).strip()]
            return [result_str.strip()]
        except Exception as e:
            logger.error(f"Failed to convert diagram to mermaid: {e}")
            return []

    def unload(self) -> None:
        self.client.close()
