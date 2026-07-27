import json
from pathlib import Path

from google.cloud import storage


BUCKET = "libraryimpact"
LOCAL_INDEX = Path(__file__).resolve().parent.parent / "library_index.json"
LOCAL_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library"
GCS_INDEX_BLOB = "library/index.json"
GCS_FILE_PREFIX = "library/files/"


def main() -> None:
    client = storage.Client()
    bucket = client.bucket(BUCKET)

    local_index = json.loads(LOCAL_INDEX.read_text(encoding="utf-8"))
    gcs_index_blob = bucket.blob(GCS_INDEX_BLOB)
    if gcs_index_blob.exists():
        gcs_index = json.loads(gcs_index_blob.download_as_text(encoding="utf-8"))
    else:
        gcs_index = {"folders": {}, "files": {}}

    added_meta = 0
    uploaded_files = 0

    gcs_index.setdefault("folders", {})
    gcs_index.setdefault("files", {})

    for fid, finfo in local_index.get("files", {}).items():
        local_file = LOCAL_LIBRARY_DIR / fid
        if not local_file.exists():
            continue
        blob = bucket.blob(f"{GCS_FILE_PREFIX}{fid}")
        if not blob.exists():
            blob.upload_from_filename(str(local_file))
            uploaded_files += 1
        if fid not in gcs_index["files"]:
            gcs_index["files"][fid] = finfo
            added_meta += 1

    # Merge folders too (if any local)
    for folder_id, folder in local_index.get("folders", {}).items():
        if folder_id not in gcs_index["folders"]:
            gcs_index["folders"][folder_id] = folder

    gcs_index_blob.upload_from_string(
        json.dumps(gcs_index, indent=2, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )
    print(f"uploaded_files={uploaded_files}, added_meta={added_meta}")


if __name__ == "__main__":
    main()
