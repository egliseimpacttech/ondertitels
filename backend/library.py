"""Library: store and organize files (VTT, MP3, MP4) with folders."""
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.cloud import storage

from .config import BASE_DIR, GCS_BUCKET_NAME, OUTPUT_DIR, UPLOAD_DIR

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


def _cinema_cover_blob_name(file_id: str) -> str:
    return f"library/covers/cinema_{file_id}.jpg"


def upload_cinema_cover_from_path(file_id: str, jpeg_path: Path) -> None:
    """Persist Cinema cover JPEG to GCS when configured."""
    if not _use_gcs():
        return
    blob = _get_bucket().blob(_cinema_cover_blob_name(file_id))
    blob.upload_from_filename(str(jpeg_path), content_type="image/jpeg")


def download_cinema_cover_bytes(file_id: str) -> bytes | None:
    if not _use_gcs():
        return None
    blob = _get_bucket().blob(_cinema_cover_blob_name(file_id))
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def delete_cinema_cover_gcs(file_id: str) -> None:
    if not _use_gcs():
        return
    blob = _get_bucket().blob(_cinema_cover_blob_name(file_id))
    if blob.exists():
        blob.delete()


def cinema_cover_exists_on_gcs(file_id: str) -> bool:
    if not _use_gcs():
        return False
    return _get_bucket().blob(_cinema_cover_blob_name(file_id)).exists()


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
    """Remove file bytes from GCS or disk, plus Cinema cover and local caches."""
    if _use_gcs():
        bucket = _get_bucket()
        blob = bucket.blob(_file_blob_name(file_id))
        if blob.exists():
            blob.delete()
        # Cinema poster for this video (same id as library file)
        try:
            delete_cinema_cover_gcs(file_id)
        except Exception:
            pass
    else:
        p = LIBRARY_DIR / file_id
        if p.exists():
            p.unlink()
    cache_path = LIBRARY_CACHE_DIR / file_id
    if cache_path.exists():
        try:
            cache_path.unlink()
        except OSError:
            pass
    # Local temp cover from ffmpeg extract (used before upload to GCS)
    cover_local = OUTPUT_DIR / f"cinema_cover_{file_id}.jpg"
    if cover_local.exists():
        try:
            cover_local.unlink()
        except OSError:
            pass


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


def list_folder(folder_path: str = "", user_email: str = "") -> Dict[str, Any]:
    index = _load_index()
    folder_path = folder_path.strip("/")
    folders = []
    files = []
    user_email = (user_email or "").strip().lower()
    
    for folder_id, folder_info in index.get("folders", {}).items():
        if folder_info.get("parent", "") == folder_path:
            # Check access control
            allowed_emails = folder_info.get("allowed_emails", [])
            if allowed_emails and user_email not in [e.strip().lower() for e in allowed_emails]:
                continue
            folders.append({
                "id": folder_id, 
                "name": folder_info["name"], 
                "path": f"{folder_path}/{folder_info['name']}".strip("/"),
                "allowed_emails": allowed_emails
            })
    
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


def create_folder(name: str, parent_path: str = "", allowed_emails: List[str] = None) -> Dict[str, Any]:
    index = _load_index()
    folder_id = str(uuid.uuid4())
    parent_path = parent_path.strip("/")
    folder_data = {"name": name, "parent": parent_path}
    if allowed_emails:
        folder_data["allowed_emails"] = [e.strip().lower() for e in allowed_emails if e.strip()]
    index.setdefault("folders", {})[folder_id] = folder_data
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


def update_folder_permissions(folder_id: str, allowed_emails: List[str]) -> bool:
    index = _load_index()
    if folder_id not in index.get("folders", {}):
        return False
    index["folders"][folder_id]["allowed_emails"] = [e.strip().lower() for e in allowed_emails if e.strip()]
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
    file_type = {".vtt": "vtt", ".txt": "text", ".mp3": "audio", ".mp4": "video", ".wav": "audio"}.get(suffix, "other")
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


def set_cinema_metadata(
    file_id: str,
    *,
    public: bool,
    title: str,
    description: str,
    cover_type: str,
    cover_second: float,
    subtitles: Dict[str, str],
    has_cinema_cover: bool | None = None,
) -> bool:
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
    if has_cinema_cover is not None:
        entry["cinema_has_cover"] = bool(has_cinema_cover)
    entry["cinema_updated_at"] = time.time()
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


def folder_path_exists(folder_path: str) -> bool:
    """True for root (empty), or if a folder with this full path exists in the index."""
    folder_path = (folder_path or "").strip().strip("/")
    if not folder_path:
        return True
    index = _load_index()
    for finfo in index.get("folders", {}).values():
        p = f"{finfo.get('parent', '')}/{finfo['name']}".strip("/")
        if p == folder_path:
            return True
    return False


def move_file_detailed(file_id: str, target_folder: str) -> tuple[bool, str | None]:
    """
    Move a file to target_folder (path string, '' = root).
    Returns (success, error_code): error_code is not_found | bad_folder | duplicate | None.
    """
    index = _load_index()
    if file_id not in index.get("files", {}):
        return False, "not_found"
    target_folder = (target_folder or "").strip().strip("/")
    if not folder_path_exists(target_folder):
        return False, "bad_folder"
    cur = (index["files"][file_id].get("folder") or "").strip().strip("/")
    if cur == target_folder:
        return True, None
    name = index["files"][file_id]["name"]
    for fid, finfo in index.get("files", {}).items():
        if fid == file_id:
            continue
        if (finfo.get("folder") or "").strip().strip("/") == target_folder and finfo.get("name") == name:
            return False, "duplicate"
    index["files"][file_id]["folder"] = target_folder
    _save_index(index)
    return True, None


def move_file(file_id: str, target_folder: str) -> bool:
    ok, _err = move_file_detailed(file_id, target_folder)
    return ok


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


def _norm_lib_path(p: str) -> str:
    return (p or "").strip().strip("/")


def duplicate_file(file_id: str) -> Dict[str, Any] | None:
    """Copy a library file into the same folder with a unique ``(copie)`` name."""
    index = _load_index()
    if file_id not in index.get("files", {}):
        return None
    if _read_file_bytes(file_id) is None:
        return None
    src = index["files"][file_id]
    folder_path = _norm_lib_path(src.get("folder", ""))
    orig_name = src.get("name", "fichier")
    stem = Path(orig_name).stem
    suffix = Path(orig_name).suffix
    existing = {
        finfo.get("name")
        for _fid, finfo in index["files"].items()
        if _norm_lib_path(finfo.get("folder", "")) == folder_path
    }
    new_name = f"{stem} (copie){suffix}"
    n = 2
    while new_name in existing:
        new_name = f"{stem} (copie {n}){suffix}"
        n += 1
    return copy_file(file_id, folder_path, new_name)


def _duplicate_folder_tree(src_path: str, dst_path: str) -> None:
    src_path = _norm_lib_path(src_path)
    dst_path = _norm_lib_path(dst_path)
    index = _load_index()
    for fid, finfo in list(index.get("files", {}).items()):
        if _norm_lib_path(finfo.get("folder", "")) != src_path:
            continue
        if _read_file_bytes(fid) is None:
            continue
        copy_file(fid, dst_path, finfo.get("name"))

    index = _load_index()
    for _sub_id, sub in list(index.get("folders", {}).items()):
        if _norm_lib_path(sub.get("parent", "")) != src_path:
            continue
        sub_name = sub["name"]
        src_sub = f"{src_path}/{sub_name}".strip("/")
        new_sub_id = str(uuid.uuid4())
        index = _load_index()
        index["folders"][new_sub_id] = {"name": sub_name, "parent": dst_path}
        _save_index(index)
        dst_sub = f"{dst_path}/{sub_name}".strip("/")
        _duplicate_folder_tree(src_sub, dst_sub)


def duplicate_folder(folder_id: str) -> bool:
    """Deep-copy a folder tree as a sibling ``(copie)`` folder."""
    index = _load_index()
    if folder_id not in index.get("folders", {}):
        return False
    info = index["folders"][folder_id]
    parent = _norm_lib_path(info.get("parent", ""))
    old_name = info["name"]
    old_path = f"{parent}/{old_name}".strip("/") if parent else old_name

    sibling_names = {
        finfo["name"]
        for _fid, finfo in index["folders"].items()
        if _norm_lib_path(finfo.get("parent", "")) == parent
    }
    new_name = f"{old_name} (copie)"
    n = 2
    while new_name in sibling_names:
        new_name = f"{old_name} (copie {n})"
        n += 1

    new_folder_id = str(uuid.uuid4())
    index["folders"][new_folder_id] = {"name": new_name, "parent": parent}
    _save_index(index)
    new_path = f"{parent}/{new_name}".strip("/") if parent else new_name

    _duplicate_folder_tree(old_path, new_path)
    return True
