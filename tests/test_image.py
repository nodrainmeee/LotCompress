import hashlib
import threading
from pathlib import Path

from PIL import Image

from lotcompress.core.models import Task, Status
from lotcompress.core.output import output_path
from lotcompress.image.compressor import process_task
from lotcompress.presets import PRESETS


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_compress_image_to_compresses(tmp_path: Path):
    src_dir = tmp_path / "photos" / "sub"; src_dir.mkdir(parents=True)
    src = src_dir / "photo.jpg"
    Image.effect_mandelbrot((2400, 1600), (-2, -1.2, 1, 1.2), 100).convert("RGB").save(src, quality=95)
    before = _md5(src)

    r = process_task(Task(src, tmp_path / "photos"), PRESETS["Web"], threading.Event())

    assert r.status == Status.DONE, r.message
    assert r.output_path == tmp_path / "photos" / "Compressés" / "sub" / "photo.webp"
    assert r.output_size < r.original_size
    with Image.open(r.output_path) as im:
        assert max(im.size) <= 1920
    assert _md5(src) == before  # Original intact


def test_custom_output_dir(tmp_path: Path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (300, 200), (255, 0, 0, 128)).save(src)
    out = tmp_path / "sortie"
    r = process_task(Task(src, tmp_path), PRESETS["WhatsApp"].with_(output_dir=str(out)), threading.Event())
    assert r.status in (Status.DONE, Status.KEPT)
    assert r.output_path.parent == out


def test_corrupt_file_reported(tmp_path: Path):
    bad = tmp_path / "bad.jpg"; bad.write_bytes(b"\xff\xd8\xffnope")
    r = process_task(Task(bad, tmp_path), PRESETS["Web"], threading.Event())
    assert r.status == Status.ERROR and r.message


def test_name_collision(tmp_path: Path):
    src = tmp_path / "x.jpg"; src.write_bytes(b"")
    target = tmp_path / "Compressés" / "x.jpg"; target.parent.mkdir(); target.write_bytes(b"1")
    assert output_path(src, tmp_path, "JPEG", False).name == "x (2).jpg"
