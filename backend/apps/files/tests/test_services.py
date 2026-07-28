"""Low-level attachment service boundary tests."""
from __future__ import annotations

import pytest

from apps.files import policy
from apps.files.services import scan_with_clamav


class _FakeClamAVSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._responses = iter([b"stream: OK\0"])

    def __enter__(self) -> _FakeClamAVSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, _size: int) -> bytes:
        return next(self._responses, b"")


def test_clamav_instream_uses_network_order_chunks_and_zero_terminator(
    monkeypatch,
) -> None:
    """Catch little-endian lengths or a terminator merged into a data chunk."""
    fake_socket = _FakeClamAVSocket()
    monkeypatch.setattr(
        "apps.files.services.socket.create_connection",
        lambda *_args, **_kwargs: fake_socket,
    )

    result = scan_with_clamav(b"clam")

    assert result == ("clean", None)
    assert fake_socket.sent == [
        b"zINSTREAM\0",
        b"\x00\x00\x00\x04clam",
        b"\x00\x00\x00\x00",
    ]


class _ChunkOnlyUpload:
    def chunks(self, chunk_size: int | None = None):
        assert chunk_size == 64 * 1024
        yield b"abc"
        yield b"def"

    def read(self) -> bytes:
        pytest.fail("upload reader bypassed Django's bounded chunk iterator")


def test_upload_reader_rejects_the_chunk_that_crosses_the_size_cap(
    monkeypatch,
) -> None:
    """Catch unbounded read() calls or trusting declared upload size alone."""
    monkeypatch.setattr(policy, "MAX_ATTACHMENT_SIZE_BYTES", 5)

    with pytest.raises(
        policy.AttachmentValidationError,
        match="Each file must be 20 MiB or smaller",
    ):
        policy.read_attachment_bounded(_ChunkOnlyUpload())
