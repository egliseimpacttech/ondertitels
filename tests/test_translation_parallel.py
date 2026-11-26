import threading
import time
from types import SimpleNamespace

from backend import translation


def test_lingala_translation_runs_concurrently_and_preserves_segment_order(monkeypatch):
    active = 0
    peak_active = 0
    lock = threading.Lock()
    progress = []

    class FakeCompletions:
        def create(self, *, model, messages):
            nonlocal active, peak_active
            text = messages[-1]["content"]
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                time.sleep({"first": 0.06, "second": 0.01, "third": 0.03, "fourth": 0.02}[text])
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=f"lingala:{text}")
                        )
                    ]
                )
            finally:
                with lock:
                    active -= 1

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(translation, "OpenAI", lambda api_key: fake_client)
    monkeypatch.setattr(translation, "_translation_cache", {})

    results = translation._translate_openai(
        ["first", "second", "third", "fourth"],
        "ln",
        "",
        "test-key",
        progress_callback=lambda done, total: progress.append((done, total)),
    )

    assert results == [
        "lingala:first",
        "lingala:second",
        "lingala:third",
        "lingala:fourth",
    ]
    assert 1 < peak_active <= translation.LINGALA_TRANSLATION_CONCURRENCY
    assert sorted(done for done, _ in progress) == [1, 2, 3, 4]
    assert all(total == 4 for _, total in progress)
