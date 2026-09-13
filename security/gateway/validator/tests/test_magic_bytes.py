from app.magic_bytes import sniff_audio_payload, sniff_extension

JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
WAV_HEADER = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"\x00" * 20
MP3_HEADER_ID3 = b"ID3" + b"\x00" * 20
MP3_HEADER_FRAME_SYNC = bytes([0xFF, 0xFB]) + b"\x00" * 20
MP4_HEADER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20
PLAIN_TEXT = b"the quick brown fox jumps over the lazy dog\n"


def test_valid_jpeg_matches_declared_extension():
    result = sniff_extension(".jpg", JPEG_HEADER)
    assert result.valid


def test_valid_png_matches_declared_extension():
    result = sniff_extension(".png", PNG_HEADER)
    assert result.valid


def test_valid_wav_matches_declared_extension():
    result = sniff_extension(".wav", WAV_HEADER)
    assert result.valid


def test_valid_mp3_id3_matches_declared_extension():
    result = sniff_extension(".mp3", MP3_HEADER_ID3)
    assert result.valid


def test_valid_mp3_frame_sync_matches_declared_extension():
    result = sniff_extension(".mp3", MP3_HEADER_FRAME_SYNC)
    assert result.valid


def test_valid_mp4_matches_declared_extension():
    result = sniff_extension(".mp4", MP4_HEADER)
    assert result.valid


def test_plain_text_matches_txt_extension():
    result = sniff_extension(".txt", PLAIN_TEXT)
    assert result.valid


def test_disallowed_extension_is_rejected_outright():
    result = sniff_extension(".exe", b"MZ" + b"\x00" * 20)
    assert not result.valid


def test_png_renamed_to_mp4_is_rejected():
    """Extension-spoofing: a PNG's actual bytes claiming to be an .mp4."""
    result = sniff_extension(".mp4", PNG_HEADER)
    assert not result.valid


def test_executable_renamed_to_txt_is_rejected():
    """A binary with a NUL byte can't be genuine text, regardless of extension."""
    fake_binary = b"MZ\x00\x00" + b"\x90" * 20
    result = sniff_extension(".txt", fake_binary)
    assert not result.valid


def test_audio_payload_accepts_wav_bytes():
    result = sniff_audio_payload(WAV_HEADER)
    assert result.valid and result.detected_type == ".wav"


def test_audio_payload_accepts_mp3_bytes():
    result = sniff_audio_payload(MP3_HEADER_ID3)
    assert result.valid and result.detected_type == ".mp3"


def test_audio_payload_rejects_non_audio_bytes():
    """Modality says 'audio' but the decoded payload is actually a JPEG."""
    result = sniff_audio_payload(JPEG_HEADER)
    assert not result.valid
