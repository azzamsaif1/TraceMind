import pytest

from rusted_recall.config import Settings
from rusted_recall.storage import get_storage
from rusted_recall.storage.base import ObjectKeys, sanitize_filename
from rusted_recall.validation import validate_repaired_image


def test_object_key_namespace():
    keys = ObjectKeys("ws1")
    k = keys.asset_original("a1", "v1", "hero.png")
    assert k == "rusted-recall/workspaces/ws1/assets/a1/versions/v1/original/hero.png"
    assert keys.recall_report("r1", "json").endswith("reports/final-report.json")


def test_sanitize_filename_blocks_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert "/" not in sanitize_filename("a/b/c.png")
    assert sanitize_filename("  ") == "file"


def test_local_storage_roundtrip_and_readback(tmp_path, blue_png):
    settings = Settings(app_env="development", storage_backend="local", local_storage_dir=str(tmp_path))
    storage = get_storage(settings)
    assert storage.is_system_of_record is False
    keys = ObjectKeys("ws1")
    key = keys.asset_original("a1", "v1", "hero.png")
    stored = storage.put_bytes(key, blue_png, "image/png")
    assert stored.sha256
    assert storage.exists(key)
    assert storage.get_bytes(key) == blue_png
    assert key in storage.list_prefix("rusted-recall/workspaces/ws1/assets")


def test_production_without_b2_refuses_local():
    from rusted_recall.storage.base import StorageConfigError

    settings = Settings(app_env="production", storage_backend="auto")
    with pytest.raises(StorageConfigError):
        get_storage(settings)


def test_validation_flags_identical_output(blue_png):
    result = validate_repaired_image(blue_png, original_bytes=blue_png, expected_mime="image/png")
    assert result.checks["differs_from_original"] is False
    assert result.passed is False


def test_validation_passes_for_changed_output(blue_png, red_png):
    result = validate_repaired_image(red_png, original_bytes=blue_png, expected_mime="image/png")
    assert result.checks["decodes"] is True
    assert result.checks["differs_from_original"] is True


def test_validation_new_claim_requires_review_when_absent(red_png):
    result = validate_repaired_image(
        red_png,
        expected_mime="image/png",
        new_claim_text="Daily Botanical Blend",
        extracted_text="some other text",
    )
    assert result.requires_human_review is True
