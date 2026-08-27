"""Low-level attachment service boundary tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from botocore.exceptions import ClientError

from apps.files import policy, services
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


class _VersionedObjectStore:
    """Model MinIO's versioned writes and key-only delete behaviour."""

    def __init__(self, *, return_version_id: bool = True) -> None:
        self.versions: dict[str, list[tuple[str, bytes, str]]] = {}
        self.delete_calls: list[dict[str, object]] = []
        self.return_version_id = return_version_id
        self._next_version = 1

    def current(self, key: str) -> tuple[str, bytes, str] | None:
        versions = self.versions.get(key, [])
        return versions[-1] if versions else None

    def put_object(self, **kwargs: object) -> dict[str, str]:
        key = str(kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and self.current(key) is not None:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        version_id = f"version-{self._next_version}"
        self._next_version += 1
        etag = f'"etag-{version_id}"'
        self.versions.setdefault(key, []).append((version_id, body, etag))
        result = {"ETag": etag}
        if self.return_version_id:
            result["VersionId"] = version_id
        return result

    def delete_object(self, **kwargs: object) -> dict[str, str]:
        self.delete_calls.append(dict(kwargs))
        key = str(kwargs["Key"])
        versions = self.versions.get(key, [])
        version_id = kwargs.get("VersionId")
        if version_id is None:
            # Real MinIO ignores DeleteObject IfMatch and removes the latest object.
            if versions:
                versions.pop()
            return {}
        for index, version in enumerate(versions):
            if version[0] == version_id:
                versions.pop(index)
                return {}
        raise ClientError(
            {"Error": {"Code": "NoSuchVersion", "Message": "missing"}},
            "DeleteObject",
        )

    def generate_presigned_url(self, *_args: object, **_kwargs: object) -> str:
        return "https://files.example.test/signed"


def test_conditional_upload_does_not_overwrite_an_existing_object(monkeypatch) -> None:
    """Catch a collision turning an upload into an overwrite."""
    store = _VersionedObjectStore()
    store.put_object(
        Bucket="mhc-attachments",
        Key="attachments/collision",
        Body=b"existing",
        ContentType="application/pdf",
    )
    existing = store.current("attachments/collision")
    monkeypatch.setattr(services, "_s3_client", lambda: store)

    with pytest.raises(ClientError):
        services.upload_to_minio(
            key="attachments/collision",
            data=b"new",
            content_type="application/pdf",
        )

    assert store.current("attachments/collision") == existing


def test_compensation_deletes_exact_version_and_preserves_later_replacement(
    monkeypatch,
) -> None:
    """Catch key-only or ETag-only cleanup deleting a replacement object."""
    store = _VersionedObjectStore()
    monkeypatch.setattr(services, "_s3_client", lambda: store)
    created = services.upload_to_minio(
        key="attachments/request-object",
        data=b"request",
        content_type="application/pdf",
    )
    store.put_object(
        Bucket=created.bucket,
        Key=created.key,
        Body=b"replacement",
        ContentType="application/pdf",
    )

    services.delete_from_minio(stored_object=created)

    current = store.current(created.key)
    assert current is not None
    assert current[1] == b"replacement"
    assert store.delete_calls == [
        {
            "Bucket": created.bucket,
            "Key": created.key,
            "VersionId": created.version_id,
        }
    ]


def test_upload_without_version_id_fails_closed_and_retains_orphan(
    monkeypatch,
    caplog,
) -> None:
    """Catch accepting an unversioned write that cannot be safely compensated."""
    store = _VersionedObjectStore(return_version_id=False)
    monkeypatch.setattr(services, "_s3_client", lambda: store)

    services.logger.addHandler(caplog.handler)
    try:
        with pytest.raises(RuntimeError, match="ownership VersionId"):
            services.upload_to_minio(
                key="attachments/unversioned-object",
                data=b"request",
                content_type="application/pdf",
            )
    finally:
        services.logger.removeHandler(caplog.handler)

    current = store.current("attachments/unversioned-object")
    assert current is not None
    assert current[1] == b"request"
    assert store.delete_calls == []
    assert "minio_put_missing_version_id" in caplog.messages


def test_cleanup_without_version_id_never_deletes_by_key_or_etag(
    monkeypatch,
    caplog,
) -> None:
    """Catch a malformed ownership handle falling back to an unsafe delete."""
    store = _VersionedObjectStore()
    monkeypatch.setattr(services, "_s3_client", lambda: store)
    created = services.upload_to_minio(
        key="attachments/request-object",
        data=b"request",
        content_type="application/pdf",
    )
    unsafe_handle = replace(created, version_id="")

    services.logger.addHandler(caplog.handler)
    try:
        with pytest.raises(RuntimeError, match="ownership VersionId"):
            services.delete_from_minio(stored_object=unsafe_handle)
    finally:
        services.logger.removeHandler(caplog.handler)

    current = store.current(created.key)
    assert current is not None
    assert current[1] == b"request"
    assert store.delete_calls == []
    assert "minio_delete_missing_version_id" in caplog.messages


def test_signed_url_uses_the_browser_reachable_object_store_endpoint(
    monkeypatch,
    settings,
) -> None:
    """Catch signed links that expose MinIO's private Docker hostname."""
    store = _VersionedObjectStore()
    endpoints: list[str | None] = []

    def fake_s3_client(*, endpoint_url: str | None = None):
        endpoints.append(endpoint_url)
        return store

    settings.AWS_S3_PUBLIC_URL = "https://files.example.test"
    monkeypatch.setattr(services, "_s3_client", fake_s3_client)

    services.generate_signed_url(key="attachments/example.pdf")

    assert endpoints == ["https://files.example.test"]
