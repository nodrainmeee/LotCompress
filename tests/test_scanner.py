from pathlib import Path

from lotcompress.core.scanner import scan, kind_of


def test_scan_recursive_kinds_and_skipped(tmp_path: Path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    for name in ("x.JPG", "a/y.png", "a/b/z.heic", "a/v.mp4", "a/b/w.MOV", "notes.txt", "a/b/doc.pdf"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "Compressés").mkdir()
    (tmp_path / "Compressés" / "old.jpg").write_bytes(b"x")  # Ne doit pas être re-traité

    res = scan([tmp_path])
    found = {t.source.relative_to(tmp_path).as_posix(): t.kind for t in res.tasks}
    assert found == {"x.JPG": "image", "a/y.png": "image", "a/b/z.heic": "image",
                     "a/v.mp4": "video", "a/b/w.MOV": "video"}
    assert sorted(p.name for p in res.skipped) == ["doc.pdf", "notes.txt"]
    assert all(t.root == tmp_path for t in res.tasks)


def test_scan_single_file_and_duplicates(tmp_path: Path):
    f = tmp_path / "p.webp"; f.write_bytes(b"x")
    res = scan([f, f, tmp_path])
    assert len(res.tasks) == 1 and res.tasks[0].root == tmp_path


def test_kind_of():
    assert kind_of(Path("a.tiff")) == "image" and kind_of(Path("a.webm")) == "video"
    assert kind_of(Path("a.gif")) is None
