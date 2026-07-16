import io
from pathlib import Path

from PIL import Image

from finreportparser.types import BBox


def resize_pil(
    image_input: Image.Image | str | Path | bytes,
    max_edge: int = 768
) -> Image.Image:
    clamped_max_edge = max(512, min(768, max_edge))

    if isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    elif isinstance(image_input, bytes):
        img = Image.open(io.BytesIO(image_input))
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise TypeError("Unsupported image input type")

    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest <= clamped_max_edge:
        return img

    scale = clamped_max_edge / longest
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return img

def resize_image_bytes(
    image_input: Image.Image | str | Path | bytes,
    max_edge: int = 768,
    format: str = "JPEG"
) -> bytes:
    img = resize_pil(image_input, max_edge)
    out_io = io.BytesIO()
    img.save(out_io, format=format)
    return out_io.getvalue()

def crop_image_bytes(
    image_input: bytes,
    bbox: BBox,
    pad: int = 4,
    format: str = "PNG"
) -> bytes:
    img = Image.open(io.BytesIO(image_input))
    w, h = img.size

    x0 = max(0, int(bbox.x0) - pad)
    y0 = max(0, int(bbox.y0) - pad)
    x1 = min(w, int(bbox.x1) + pad)
    y1 = min(h, int(bbox.y1) + pad)

    cropped = img.crop((x0, y0, x1, y1))
    out_io = io.BytesIO()
    cropped.save(out_io, format=format)
    return out_io.getvalue()
