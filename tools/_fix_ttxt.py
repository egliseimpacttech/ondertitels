# -*- coding: utf-8 -*-
from pathlib import Path

p = Path("frontend/index.html")
raw = p.read_bytes()
t = raw.decode("utf-8").replace("\r\n", "\n")

old = """            beginJobUI(
              document.getElementById('transcribeTextResult'),
              document.getElementById('transcribeTextBtn'),
              'Upload voorbereiden… (signaal is binnen)',
            );
            await yieldForPaint();
            const contentType = transcribeTextSelectedFile.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', transcribeTextSelectedFile.name);
            urlForm.append('content_type', contentType);
            const initRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: urlForm });
            if (!initRes.ok) {
              let detail = initRes.statusText || String(initRes.status);
              try {
                const errBody = await initRes.json();
                if (errBody.detail) detail = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
              } catch (_) {}
              throw new Error('Signed URL failed (' + initRes.status + '): ' + detail);
            }
            const initData = await initRes.json();

            await uploadToSignedUrl(initData.session_url, contentType, transcribeTextSelectedFile);

            const gcsForm = new FormData();"""

new = """            const transcribeTextResultEl = document.getElementById('transcribeTextResult');
            beginJobUI(
              transcribeTextResultEl,
              document.getElementById('transcribeTextBtn'),
              'Signaal ontvangen — uploadadres aanvragen…',
            );
            await yieldForPaint();
            let ttxtMsg = transcribeTextResultEl.querySelector('.progress-msg');
            let ttxtFill = transcribeTextResultEl.querySelector('.progress-fill');
            let ttxtBar = transcribeTextResultEl.querySelector('.progress-bar');
            const contentType = transcribeTextSelectedFile.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', transcribeTextSelectedFile.name);
            urlForm.append('content_type', contentType);
            const initRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: urlForm });
            if (!initRes.ok) {
              let detail = initRes.statusText || String(initRes.status);
              try {
                const errBody = await initRes.json();
                if (errBody.detail) detail = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
              } catch (_) {}
              throw new Error('Signed URL failed (' + initRes.status + '): ' + detail);
            }
            const initData = await initRes.json();
            if (ttxtMsg) ttxtMsg.textContent = 'Bestand uploaden naar opslag… (kan bij een grote file enkele minuten duren)';
            await uploadToSignedUrl(initData.session_url, contentType, transcribeTextSelectedFile, function (loaded, total) {
              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;
              if (ttxtFill) ttxtFill.style.width = pct + '%';
              if (ttxtBar && pct > 0) ttxtBar.classList.remove('progress-bar--waiting');
              if (ttxtMsg) {
                const mb = function (n) { return (n / 1048576).toFixed(1); };
                ttxtMsg.textContent = 'Uploaden… ' + pct + '% (' + mb(loaded) + ' / ' + mb(total) + ' MB)';
              }
            }, function (state) {
              if (!ttxtMsg) return;
              if (state === 'paused') ttxtMsg.textContent = 'Upload gepauzeerd — opnieuw proberen…';
              if (state === 'resuming') ttxtMsg.textContent = 'Verbinding hersteld — upload hervat…';
            });

            const gcsForm = new FormData();"""

if old not in t:
    raise SystemExit("block not found, snippet: " + repr(t[t.find("transcribeTextResult") : t.find("transcribeTextResult")+200]))
t = t.replace(old, new, 1)
# preserve CRLF if file had it
out = t.replace("\n", "\r\n") if b"\r\n" in raw else t
p.write_text(out, encoding="utf-8", newline="")
print("ok")
