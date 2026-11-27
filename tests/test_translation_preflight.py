from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from backend import main


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/translate",
            "raw_path": b"/api/translate",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 1234),
        }
    )


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


@pytest.mark.asyncio
async def test_translate_rejects_unsupported_language_before_starting_job(monkeypatch, tmp_path):
    tasks = []
    monkeypatch.setattr(main.asyncio, "create_task", tasks.append)
    monkeypatch.setattr(main.config, "DEEPL_API_KEY", "deepl-key")
    monkeypatch.setattr(main.config, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(main.config, "MAX_UPLOAD_BYTES", None)
    monkeypatch.setattr(main.config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main.config, "OUTPUT_DIR", tmp_path / "output")

    with pytest.raises(HTTPException) as exc_info:
        await main.translate_vtt(
            _request(),
            _upload("captions.txt", b"Hello"),
            "en,unknown",
        )

    assert exc_info.value.status_code == 400
    assert "unknown" in exc_info.value.detail
    assert not tasks
    assert not list((tmp_path / "uploads").glob("*"))


@pytest.mark.asyncio
async def test_translate_rejects_unavailable_language_provider_before_starting_job(monkeypatch, tmp_path):
    tasks = []
    monkeypatch.setattr(main.asyncio, "create_task", tasks.append)
    monkeypatch.setattr(main.config, "DEEPL_API_KEY", "deepl-key")
    monkeypatch.setattr(main.config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(main.config, "MAX_UPLOAD_BYTES", None)
    monkeypatch.setattr(main.config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main.config, "OUTPUT_DIR", tmp_path / "output")

    with pytest.raises(HTTPException) as exc_info:
        await main.translate_vtt(
            _request(),
            _upload("captions.txt", b"Hello"),
            "en,ln",
        )

    assert exc_info.value.status_code == 503
    assert "Lingala" in exc_info.value.detail
    assert not tasks
    assert not list((tmp_path / "uploads").glob("*"))


@pytest.mark.asyncio
async def test_translate_accepts_bom_crlf_vtt_after_preflight(monkeypatch, tmp_path):
    tasks = []
    monkeypatch.setattr(main.asyncio, "create_task", tasks.append)
    monkeypatch.setattr(main.config, "DEEPL_API_KEY", "deepl-key")
    monkeypatch.setattr(main.config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(main.config, "MAX_UPLOAD_BYTES", None)
    monkeypatch.setattr(main.config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(main, "set_job_progress", lambda *args: None)

    response = await main.translate_vtt(
        _request(),
        _upload(
            "captions.vtt",
            b"\xef\xbb\xbfWEBVTT\r\n\r\n00:00:01.000 --> 00:00:02.000\r\nHello\r\n",
        ),
        "en",
    )

    assert response["job_id"]
    assert len(tasks) == 1
    assert list((tmp_path / "uploads").glob("*.vtt"))
    tasks[0].close()


@pytest.mark.asyncio
async def test_translate_rejects_empty_text_before_starting_job(monkeypatch, tmp_path):
    tasks = []
    monkeypatch.setattr(main.asyncio, "create_task", tasks.append)
    monkeypatch.setattr(main.config, "DEEPL_API_KEY", "deepl-key")
    monkeypatch.setattr(main.config, "MAX_UPLOAD_BYTES", None)
    monkeypatch.setattr(main.config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main.config, "OUTPUT_DIR", tmp_path / "output")

    with pytest.raises(HTTPException) as exc_info:
        await main.translate_vtt(
            _request(),
            _upload("captions.txt", b" \r\n\t "),
            "en",
        )

    assert exc_info.value.status_code == 400
    assert "empty" in exc_info.value.detail.lower()
    assert not tasks
    assert not list((tmp_path / "uploads").glob("*"))


@pytest.mark.asyncio
async def test_translate_rejects_malformed_vtt_cue_before_starting_job(monkeypatch, tmp_path):
    tasks = []
    monkeypatch.setattr(main.asyncio, "create_task", tasks.append)
    monkeypatch.setattr(main.config, "DEEPL_API_KEY", "deepl-key")
    monkeypatch.setattr(main.config, "MAX_UPLOAD_BYTES", None)
    monkeypatch.setattr(main.config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main.config, "OUTPUT_DIR", tmp_path / "output")

    with pytest.raises(HTTPException) as exc_info:
        await main.translate_vtt(
            _request(),
            _upload(
                "captions.vtt",
                b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n\ninvalid --> timing\nMissing cue",
            ),
            "en",
        )

    assert exc_info.value.status_code == 400
    assert "malformed" in exc_info.value.detail.lower()
    assert not tasks
    assert not list((tmp_path / "uploads").glob("*"))
