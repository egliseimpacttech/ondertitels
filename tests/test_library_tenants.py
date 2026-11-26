import json

import pytest
from google.api_core.exceptions import Forbidden

from backend import library


@pytest.fixture
def local_library(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(library, "LIBRARY_INDEX", tmp_path / "library_index.json")
    monkeypatch.setattr(library, "LIBRARY_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(library, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(library, "_gcs_fallback_reason", None)
    monkeypatch.setattr(library, "_gcs_client", None)
    monkeypatch.setattr(library, "_gcs_bucket", None)


def test_gcs_failure_falls_back_to_tenant_local_storage(local_library, monkeypatch):
    class UnavailableBlob:
        def exists(self):
            raise Forbidden("bucket billing disabled")

    class UnavailableBucket:
        def blob(self, name):
            return UnavailableBlob()

    monkeypatch.setattr(library, "GCS_BUCKET_NAME", "temporary-placeholder")
    monkeypatch.setattr(library, "_get_bucket", lambda: UnavailableBucket())

    with library.tenant_scope("church-a", 100):
        assert library.list_folder()["files"] == []
        assert library.get_storage_status()["backend"] == "local_fallback"
        uploaded = library.upload_file(b"local copy", "sermon.vtt")
        downloaded = library.get_file(uploaded["id"])

    assert downloaded == (b"local copy", "sermon.vtt")
    assert (library.LIBRARY_DIR / "church-a" / uploaded["id"]).read_bytes() == b"local copy"


def test_gcs_write_failure_saves_file_and_index_locally(local_library, monkeypatch):
    class Blob:
        def __init__(self, name):
            self.name = name

        def exists(self):
            return self.name.endswith("/index.json")

        def download_as_text(self, encoding):
            return '{"folders": {}, "files": {}}'

        def upload_from_string(self, *args, **kwargs):
            raise Forbidden("bucket billing disabled")

    class Bucket:
        def blob(self, name):
            return Blob(name)

    monkeypatch.setattr(library, "GCS_BUCKET_NAME", "temporary-placeholder")
    monkeypatch.setattr(library, "_get_bucket", lambda: Bucket())

    with library.tenant_scope("church-a", 100):
        uploaded = library.upload_file(b"local copy", "sermon.vtt")
        assert library.get_file(uploaded["id"]) == (b"local copy", "sermon.vtt")

    assert (library.LIBRARY_DIR / "church-a" / "index.json").exists()


def test_tenant_libraries_are_isolated(local_library):
    with library.tenant_scope("church-a", 100):
        library.upload_file(b"first church", "sermon.vtt")

    with library.tenant_scope("church-b", 100):
        assert library.list_folder()["files"] == []
        library.upload_file(b"second church", "sermon.vtt")
        assert library.get_storage_usage_bytes() == len(b"second church")

    with library.tenant_scope("church-a", 100):
        assert library.get_storage_usage_bytes() == len(b"first church")
        files = library.list_folder()["files"]
        assert library.get_file(files[0]["id"])[0] == b"first church"


def test_upload_that_exceeds_storage_limit_is_rejected_without_overwriting(local_library):
    with library.tenant_scope("church-a", 4):
        library.upload_file(b"safe", "sermon.txt")

        with pytest.raises(library.StorageLimitExceeded):
            library.upload_file(b"larger", "sermon.txt")

        stored = library.list_folder()["files"]
        assert stored[0]["size"] == 4
        assert library.get_file(stored[0]["id"])[0] == b"safe"
        assert library.get_storage_usage_bytes() == 4


def test_folder_duplicate_checks_the_total_required_storage_first(local_library):
    with library.tenant_scope("church-a", 5):
        folder = library.create_folder("sermons")
        library.upload_file(b"large", "sermon.txt", "sermons")

        with pytest.raises(library.StorageLimitExceeded):
            library.duplicate_folder(folder["id"])

        assert [item["name"] for item in library.list_folder()["folders"]] == ["sermons"]
        assert library.get_storage_usage_bytes() == 5


def test_ministry_keeps_access_to_the_legacy_library(local_library):
    legacy_file_id = "legacy-file-id"
    library.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    (library.LIBRARY_DIR / legacy_file_id).write_bytes(b"legacy")
    library.LIBRARY_INDEX.write_text(
        json.dumps(
            {
                "folders": {},
                "files": {
                    legacy_file_id: {
                        "name": "legacy.txt",
                        "type": "text",
                        "folder": "",
                        "size": 6,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with library.tenant_scope(library.LEGACY_TENANT_ID, None):
        assert library.get_file(legacy_file_id) == (b"legacy", "legacy.txt")
        library.upload_file(b"new", "new.txt")

    assert (library.LIBRARY_DIR / library.LEGACY_TENANT_ID / "index.json").exists()
