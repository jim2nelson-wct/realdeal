from pathlib import Path

import config
from PIL import Image

GENERIC_TYPES = {
    ".pdf": "pdf",
    ".ps": "ps",
    ".eps": "eps",
    ".psd": "psd",
}


def make_thumb(artwork_path: Path, job_dir: Path):
    ext = artwork_path.suffix.lower()
    target = job_dir / "thumb.png"

    if ext not in config.RASTER_EXTENSIONS:
        return None

    with Image.open(artwork_path) as img:
        img = img.convert("RGB")
        img.thumbnail((320, 320))
        img.save(target, "PNG")
        return target
