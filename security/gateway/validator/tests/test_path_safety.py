from app.path_safety import has_traversal_sequence, is_confined_path, safe_extension


def test_plain_filename_is_safe():
    assert safe_extension("clip.mp4") == ".mp4"


def test_traversal_filename_is_rejected():
    assert safe_extension("../../etc/passwd.mp4") is None


def test_absolute_path_filename_is_rejected():
    assert safe_extension("/etc/passwd") is None


def test_windows_style_traversal_is_rejected():
    assert safe_extension("..\\..\\windows\\system32\\evil.mp4") is None


def test_empty_filename_is_rejected():
    assert safe_extension("") is None
    assert safe_extension(None) is None


def test_has_traversal_sequence_detects_dotdot():
    assert has_traversal_sequence("../secret")


def test_confined_path_inside_root(tmp_path):
    root = tmp_path / "shared_volume"
    root.mkdir()
    target = root / "tmp" / "frame.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"data")
    assert is_confined_path(str(target), str(root))


def test_confined_path_rejects_escape(tmp_path):
    root = tmp_path / "shared_volume"
    root.mkdir()
    outside = tmp_path / "etc" / "passwd"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"data")
    assert not is_confined_path(str(outside), str(root))


def test_confined_path_rejects_dotdot_escape(tmp_path):
    root = tmp_path / "shared_volume"
    root.mkdir()
    escape_attempt = str(root) + "/../../etc/passwd"
    assert not is_confined_path(escape_attempt, str(root))


def test_confined_path_requires_absolute():
    assert not is_confined_path("relative/path.mp4", "/shared_volume")
