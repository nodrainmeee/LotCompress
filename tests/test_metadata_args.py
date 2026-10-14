import pytest

from lotcompress.metadata.exiftool import BlockedTagError, check_args
from lotcompress.metadata.operations import MetaOps, build_args
from lotcompress.metadata import profiles


def test_build_args_image_normal():
    a = build_args(MetaOps(remove_gps=True, title="Titre", author="Moi", keywords=["a", "b"],
                           date="2024:05:01 10:20:30", orientation=6), video=False)
    assert "-gps:all=" in a and "-XMP-dc:Title=Titre" in a and "-EXIF:Artist=Moi" in a
    assert "-IPTC:Keywords+=a" in a and "-AllDates=2024:05:01 10:20:30" in a
    assert "-EXIF:Orientation#=6" in a


def test_build_args_video_normal():
    a = build_args(MetaOps(title="T", date="2024:05:01 10:20:30", orientation=6, keywords=["x", "y"]), video=True)
    assert "-ItemList:Title=T" in a and "-Keys:Keywords=x, y" in a
    assert "-api" in a and "QuickTimeUTC" in a and "-QuickTime:CreateDate=2024:05:01 10:20:30" in a
    assert "-Rotation=90" in a


def test_removal_of_camera_tags_allowed():
    a = build_args(MetaOps(remove_camera=True), video=False)
    assert "-Make=" in a and "-Model=" in a and "-LensModel=" in a
    check_args(["-Make=", "-Model=", "-LensModel=", "-XMP:Lens*="])


@pytest.mark.parametrize("args", [
    ["-Make=Canon"], ["-Model=EOS R5"], ["-EXIF:Model=D850"], ["-LensModel=50mm"], ["-LensMake=Sigma"],
    ["-XMP-aux:Lens=x"], ["-Keys:Make=Apple"], ["-CameraModelName=x"],
    ["-Make+=x"], ["-Model+=x"], ["-Make<Software"], ["-Model<Artist"], ["-LensModel<Comment"],
])
def test_check_args_blocks_camera_writes(args):
    with pytest.raises(BlockedTagError):
        check_args(args)


@pytest.mark.parametrize("tags", [{"Make": "Nikon"}, {"EXIF:Model": "x"}, {"XMP-aux:Lens": "x"},
                                  {"LensMake": "x"}, {"Keys:Model": "iPhone"}])
def test_custom_tags_blocked(tags):
    with pytest.raises(BlockedTagError):
        build_args(MetaOps(custom_tags=tags), video=False)


def test_profile_with_blocked_tag_rejected(tmp_path):
    (tmp_path / "p.json").write_text('{"name": "p", "operations": {"custom_tags": {"Make": "Leica"}}}')
    with pytest.raises(BlockedTagError):
        profiles.load_profile("p", base=tmp_path)


def test_newline_flattened_in_values():
    a = build_args(MetaOps(title="ok\n-Model=iPhone", author="a\r\nb", keywords=["k\n-Make=X"]), video=False)
    assert "-XMP-dc:Title=ok -Model=iPhone" in a
    assert not any(x.startswith("-Model=iPhone") for x in a)
    assert all("\n" not in x and "\r" not in x for x in a)
    assert "-EXIF:Artist=a b" in a


@pytest.mark.parametrize("bad", ["-Title=ok\n-Model=iPhone", "-Title=a\rb", "-Title=a\x00b"])
def test_check_args_newline_raises(bad):
    with pytest.raises(Exception):
        check_args([bad])
