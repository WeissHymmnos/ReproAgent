import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from finreportparser.ocr.base import BaseTableExtractor


class MinerUTableExtractor(BaseTableExtractor):
    estimated_ram_gb: float = 4.0

    def __init__(self) -> None:
        if not shutil.which("magic-pdf"):
            raise RuntimeError(
                "MinerU (magic-pdf) is not installed or not in PATH. "
                "Please install it with `uv pip install magic-pdf` or use the paddle backend."
            )

    def extract_table(self, image: bytes | Path | Image.Image) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            img_path = temp_dir_path / "input.jpg"
            if isinstance(image, bytes):
                img_path.write_bytes(image)
            elif isinstance(image, Path):
                shutil.copy(image, img_path)
            elif isinstance(image, Image.Image):
                image.convert("RGB").save(img_path, format="JPEG")
            else:
                raise ValueError("Unsupported image type")

            config_path = temp_dir_path / "magic-pdf.json"
            config_data = {
                "table_config": {
                    "model": "tablemaster",
                    "enable": True
                }
            }
            config_path.write_text(json.dumps(config_data))

            out_dir = temp_dir_path / "output"
            cmd = [
                "magic-pdf",
                "-p", str(img_path),
                "-o", str(out_dir),
                "-m", "ocr"
            ]

            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    env={"MAGIC_PDF_CONFIG": str(config_path)}
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"MinerU failed: {e.stderr}") from e

            md_files = list(out_dir.rglob("*.md"))
            if not md_files:
                return ""

            return md_files[0].read_text(encoding="utf-8")

    def unload(self) -> None:
        pass
