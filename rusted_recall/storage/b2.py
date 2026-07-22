"""Backblaze B2 storage via the S3-compatible API (directive sections 2.2, 10).

Provides upload with content-type/length/SHA-256 metadata, read-back
verification, existence checks, prefix listing, retry with bounded exponential
backoff, and clear error mapping. Original object keys are never overwritten by
the application layer; immutability is enforced by callers using version ids.
"""
from __future__ import annotations

import time

from rusted_recall.config import Settings
from rusted_recall.hashing import sha256_bytes
from rusted_recall.logging_setup import get_logger
from rusted_recall.storage.base import (
    ObjectNotFoundError,
    ReadBackVerificationError,
    StorageBackend,
    StorageConfigError,
    StorageError,
    StoredObject,
)

logger = get_logger(__name__)

_MAX_RETRIES = 4
_BASE_DELAY = 0.5


class B2Storage(StorageBackend):
    backend_name = "backblaze-b2"
    is_system_of_record = True

    def __init__(self, settings: Settings) -> None:
        if not settings.b2_configured:
            raise StorageConfigError("B2 is not configured")
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise StorageConfigError(f"boto3 is required for B2 storage: {exc}") from exc

        self._settings = settings
        self._bucket = settings.b2_bucket_name
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.b2_s3_endpoint,
            aws_access_key_id=settings.b2_key_id,
            aws_secret_access_key=settings.b2_app_key,
            region_name=settings.b2_region,
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                signature_version="s3v4",
            ),
        )

    # --- retry helper -----------------------------------------------------
    def _with_retry(self, op_name: str, fn):  # type: ignore[no-untyped-def]
        from botocore.exceptions import ClientError, EndpointConnectionError

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                # Do not retry permanent client errors (auth, not-found, invalid).
                if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "NoSuchKey", "404"}:
                    raise self._map_error(exc) from exc
                last_exc = exc
            except EndpointConnectionError as exc:
                last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "b2 operation retrying", extra={"operation": op_name, "attempt": attempt, "delay": delay}
                )
                time.sleep(delay)
        raise self._map_error(last_exc) if last_exc else StorageError(op_name)

    @staticmethod
    def _map_error(exc: Exception) -> StorageError:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404"}:
                return ObjectNotFoundError(str(exc))
        return StorageError(str(exc))

    # --- API --------------------------------------------------------------
    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
        verify_read_back: bool = True,
    ) -> StoredObject:
        digest = sha256_bytes(data)
        meta = {"sha256": digest, "content-length": str(len(data))}
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})

        self._with_retry(
            "put_object",
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=meta,
            ),
        )

        if verify_read_back:
            read = self.get_bytes(key)
            if sha256_bytes(read) != digest:
                raise ReadBackVerificationError(
                    f"read-back hash mismatch for {key}"
                )
        logger.info("b2 object stored", extra={"b2_key": key, "content_length": len(data)})
        return StoredObject(
            key=key, size=len(data), content_type=content_type, sha256=digest, metadata=meta
        )

    def get_bytes(self, key: str) -> bytes:
        resp = self._with_retry(
            "get_object", lambda: self._client.get_object(Bucket=self._bucket, Key=key)
        )
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise self._map_error(exc) from exc

    def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def health_check(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:  # noqa: BLE001 - health check must never raise
            return False
