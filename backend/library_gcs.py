"""Library: store and organize files (VTT, MP3, MP4) with folders."""
import json
import shutil
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.cloud import storage

from .config import BASE_DIR, GCS_BUCKET_NAME, UPLOAD_DIR

LIBRARY_DIR = BASE_DIR / "library"
LIBRARY_DIR.mkdir(exist_ok=True)
LIBRARY_INDEX = BASE_DIR / "library_index.json"
LIBRARY_CACHE_DIR = UPLOAD_DIR / "library_cache"
LIBRARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_gcs_client: storage.Client | None = None
_gcs_bucket: storage.Bucket | None = None


def _use_gcs() -> bool:
    return bool((GCS_BUCKET_NAME or "").strip())


def _get_bucket() -> storage.Bucket:
    global _gcs_client, _gcs_bucket
    if _gcs_bucket is not None:
        return _gcs_bucket
    if _gcs_client is None:
        _gcs_client = storage.Client()
    _gcs_bucket = _gcs_client.bucket((GCS_BUCKET_NAME or "").strip())
    return _gcs_bucket


def _index_blob_name() -> str:
    return "library/index.json"


def _file_blob_name(file_id: str) -> str:
    return f"library/files/{file_id}"


def _read_file_bytes(file_id: str) -> bytes | None:
    if _use_gcs():
        blob = _get_bucket().blob(_file_blob_name(file_id))
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    file_path = LIBRARY_DIR / file_id
    if not file_path.exists():
        return None
    return file_path.read_bytes()


def _write_file_bytes(file_id: str, data: bytes) -> None:
    if _use_gcs():
        _get_bucket().blob(_file_blob_name(file_id)).upload_from_string(data)
        return
    (LIBRARY_DIR / file_id).write_bytes(data)


def _write_file_from_path(file_id: str, source_path: Path) -> None:
    if _use_gcs():
        _get_bucket().blob(_file_blob_name(file_id)).upload_from_filename(str(source_path))
        return
    shutil.copyfile(str(source_path), str(LIBRARY_DIR / file_id))


def _delete_file_storage(file_id: str) -> None:
    if _use_gcs():
        blob = _get_bucket().blob(_file_blob_name(file_id))
        if blob.exists():
            blob.delete()
    else:
        p = LIBRARY_DIR / file_id
        if p.exists():
            p.unlink()
    cache_path = LIBRARY_CACHE_DIR / file_id
    if cache_path.exists():
        cache_path.unlink()


def _load_index() -> Dict[str, Any]:
    """Load the library index (folder structure and file metadata)."""
    if _use_gcs():
        blob = _get_bucket().blob(_index_blob_name())
        if blob.exists():
            return json.loads(blob.download_as_text(encoding="utf-8"))
        return {"folders": {}, "files": {}}
    if LIBRARY_INDEX.exists():
        return json.loads(LIBRARY_INDEX.read_text(encoding="utf-8"))
    return {"folders": {}, "files": {}}


def _save_index(index: Dict[str, Any]) -> None:
    """Save the library index."""
    payload = json.dumps(index, indent=2, ensure_ascii=False)
    if _use_gcs():
        _get_bucket().blob(_index_blob_name()).upload_from_string(
            payload,
            content_type="application/json; charset=utf-8",
        )
        return
    LIBRARY_INDEX.write_text(payload, encoding="utf-8")


def list_folder(folder_path: str = "") -> Dict[str, Any]:
    index = _load_index()
    folder_path = folder_path.strip("/")
    folders = []
    files = []
    for folder_id, folder_info in index.get("folders", {}).items():
        if folder_info.get("parent", "") == folder_path:
            folders.append({"id": folder_id, "name": folder_info["name"], "path": f"{folder_path}/{folder_info['name']}".strip("/")})
    for file_id, file_info in index.get("files", {}).items():
        if file_info.get("folder", "") == folder_path:
            files.append({
                "id": file_id,
                "name": file_info["name"],
                "type": file_info["type"],
                "size": file_info.get("size", 0),
                "cinema_public": bool(file_info.get("cinema_public", False)),
                "cinema_title": file_info.get("cinema_title") or "",
            })
    return {"path": folder_path, "folders": sorted(folders, key=lambda x: x["name"].lower()), "files": sorted(files, key=lambda x: x["name"].lower())}


def create_folder(name: str, parent_path: str = "") -> Dict[str, Any]:
    index = _load_index()
    folder_id = str(uuid.uuid4())
    parent_path = parent_path.strip("/")
    index.setdefault("folders", {})[folder_id] = {"name": name, "parent": parent_path}
    _save_index(index)
    return {"id": folder_id, "name": name, "path": f"{parent_path}/{name}".strip("/")}


def delete_folder(folder_id: str) -> bool:
    index = _load_index()
    if folder_id not in index.get("folders", {}):
        return False
    folder_info = index["folders"][folder_id]
    folder_path = f"{folder_info.get('parent', '')}/{folder_info['name']}".strip("/")
    files_to_delete = [fid for fid, finfo in index.get("files", {}).items() if finfo.get("folder", "").startswith(folder_path)]
    for fid in files_to_delete:
        try:
            _delete_file_storage(fid)
        except Exception:
            pass
        del index["files"][fid]
    folders_to_delete = [fid for fid, finfo in index.get("folders", {}).items() if finfo.get("parent", "").startswith(folder_path) or fid == folder_id]
    for fid in folders_to_delete:
        if fid in index["folders"]:
            del index["folders"][fid]
    _save_index(index)
    return True


def upload_file(file_data: bytes, filename: str, folder_path: str = "", overwrite: bool = True) -> Dict[str, Any]:
    index = _load_index()
    folder_path = folder_path.strip("/")
    if overwrite:
        for existing_id, existing_info in index.get("files", {}).items():
            if existing_info.get("folder", "") == folder_path and existing_info.get("name") == filename:
                _write_file_bytes(existing_id, file_data)
                existing_info["size"] = len(file_data)
                _save_index(index)
                return {"id": existing_id, "name": filename, "type": existing_info.get("type", "other"), "overwritten": True}
    file_id = str(uuid.uuid4())
    suffix = Path(filename).suffix.lower()
    file_type = {".vtt": "vtt", ".txt": "text", ".mp3": "audio", ".mp4": "video", ".wav": "audio", ".m4a": "audio"}.get(suffix, "other")
    _write_file_bytes(file_id, file_data)
    index.setdefault("files", {})[file_id] = {"name": filename, "type": file_type, "folder": folder_path, "size": len(file_data)}
    _save_index(index)
    return {"id": file_id, "name": filename, "type": file_type, "overwritten": False}


def upload_file_from_path(source_path: Path, filename: str, folder_path: str = "", overwrite: bool = True) -> Dict[str, Any]:
    index = _load_index()
    folder_path = folder_path.strip("/")
    size = source_path.stat().st_size
    if overwrite:
        for existing_id, existing_info in index.get("files", {}).items():
            if existing_info.get("folder", "") == folder_path and existing_info.get("name") == filename:
                _write_file_from_path(existing_id, source_path)
                existing_info["size"] = size
                _save_index(index)
                return {"id": existing_id, "name": filename, "type": existing_info.get("type", "other"), "overwritten": True}
    file_id = str(uuid.uuid4())
    suffix = Path(filename).suffix.lower()
    file_type = {".vtt": "vtt", ".txt": "text", ".mp3": "audio", ".mp4": "video", ".wav": "audio", ".m4a": "audio"}.get(suffix, "other")
    _write_file_from_path(file_id, source_path)
    index.setdefault("files", {})[file_id] = {"name": filename, "type": file_type, "folder": folder_path, "size": size}
    _save_index(index)
    return {"id": file_id, "name": filename, "type": file_type, "overwritten": False}


def get_file(file_id: str) -> Optional[tuple]:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return None
    data = _read_file_bytes(file_id)
    if data is None:
        return None
    file_info = index["files"][file_id]
    return data, file_info["name"]


def get_file_path(file_id: str) -> Optional[tuple[Path, str]]:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return None
    file_info = index["files"][file_id]
    if _use_gcs():
        blob = _get_bucket().blob(_file_blob_name(file_id))
        if not blob.exists():
            return None
        local_path = LIBRARY_CACHE_DIR / file_id
        blob.download_to_filename(str(local_path))
        return local_path, file_info["name"]
    file_path = LIBRARY_DIR / file_id
    if not file_path.exists():
        return None
    return file_path, file_info["name"]


def delete_file(file_id: str) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    try:
        _delete_file_storage(file_id)
    except Exception:
        pass
    del index["files"][file_id]
    _save_index(index)
    return True


def rename_file(file_id: str, new_name: str) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    index["files"][file_id]["name"] = new_name
    _save_index(index)
    return True


def set_cinema_public(file_id: str, is_public: bool) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    index["files"][file_id]["cinema_public"] = bool(is_public)
    _save_index(index)
    return True


def get_file_entry(file_id: str) -> Optional[Dict[str, Any]]:
    index = _load_index()
    return index.get("files", {}).get(file_id)


def list_all_vtt_files() -> List[Dict[str, Any]]:
    index = _load_index()
    out: List[Dict[str, Any]] = []
    for f_id, finfo in index.get("files", {}).items():
        if finfo.get("type") != "vtt":
            continue
        out.append({"id": f_id, "name": finfo.get("name", ""), "folder": finfo.get("folder", "")})
    out.sort(key=lambda x: (x["folder"].lower(), x["name"].lower()))
    return out


def set_cinema_metadata(file_id: str, *, public: bool, title: str, description: str, cover_type: str, cover_second: float, subtitles: Dict[str, str]) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    entry = index["files"][file_id]
    entry["cinema_public"] = bool(public)
    entry["cinema_title"] = (title or "").strip() or entry.get("name", "Video")
    entry["cinema_description"] = (description or "").strip()
    entry["cinema_cover_type"] = cover_type if cover_type in ("frame", "upload") else "frame"
    entry["cinema_cover_second"] = float(cover_second)
    entry["cinema_subtitles"] = dict(subtitles or {})
    _save_index(index)
    return True


def update_file(file_id: str, file_data: bytes, filename: str | None = None) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    if _read_file_bytes(file_id) is None:
        return False
    _write_file_bytes(file_id, file_data)
    index["files"][file_id]["size"] = len(file_data)
    if filename:
        index["files"][file_id]["name"] = filename
        suffix = Path(filename).suffix.lower()
        index["files"][file_id]["type"] = {".vtt": "vtt", ".txt": "text", ".mp3": "audio", ".mp4": "video", ".wav": "audio", ".m4a": "audio"}.get(suffix, "other")
    _save_index(index)
    return True


def rename_folder(folder_id: str, new_name: str) -> bool:
    index = _load_index()
    if folder_id not in index.get("folders", {}):
        return False
    old_info = index["folders"][folder_id]
    old_path = f"{old_info.get('parent', '')}/{old_info['name']}".strip("/")
    new_path = f"{old_info.get('parent', '')}/{new_name}".strip("/")
    index["folders"][folder_id]["name"] = new_name
    for fid, finfo in index.get("folders", {}).items():
        if finfo.get("parent", "").startswith(old_path):
            finfo["parent"] = new_path + finfo["parent"][len(old_path):]
    for fid, finfo in index.get("files", {}).items():
        if finfo.get("folder", "").startswith(old_path):
            finfo["folder"] = new_path + finfo["folder"][len(old_path):]
    _save_index(index)
    return True


def move_file(file_id: str, target_folder: str) -> bool:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False
    index["files"][file_id]["folder"] = target_folder.strip("/")
    _save_index(index)
    return True


def copy_file(file_id: str, target_folder: str, new_filename: str | None = None) -> Dict[str, Any] | None:
    index = _load_index()
    if file_id not in index.get("files", {}):
        return None
    file_info = index["files"][file_id]
    source_bytes = _read_file_bytes(file_id)
    if source_bytes is None:
        return None
    new_file_id = str(uuid.uuid4())
    try:
        _write_file_bytes(new_file_id, source_bytes)
    except Exception:
        return None
    filename = new_filename or file_info["name"]
    target_folder = target_folder.strip("/")
    index.setdefault("files", {})[new_file_id] = {"name": filename, "folder": target_folder, "type": file_info["type"], "size": file_info.get("size", 0)}
    _save_index(index)
    return {"id": new_file_id, "name": filename, "folder": target_folder, "type": file_info["type"]}


def move_folder(folder_id: str, target_parent: str) -> bool:
    index = _load_index()
    if folder_id not in index.get("folders", {}):
        return False
    folder_info = index["folders"][folder_id]
    old_parent = folder_info.get("parent", "")
    old_path = f"{old_parent}/{folder_info['name']}".strip("/")
    new_path = f"{target_parent}/{folder_info['name']}".strip("/")
    index["folders"][folder_id]["parent"] = target_parent.strip("/")
    for fid, finfo in index.get("folders", {}).items():
        if finfo.get("parent", "").startswith(old_path + "/"):
            finfo["parent"] = new_path + finfo["parent"][len(old_path):]
    for fid, finfo in index.get("files", {}).items():
        if finfo.get("folder", "").startswith(old_path + "/") or finfo.get("folder", "") == old_path:
            finfo["folder"] = new_path + finfo["folder"][len(old_path):]
    _save_index(index)
    return True
