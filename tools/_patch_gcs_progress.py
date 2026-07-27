from pathlib import Path

p = Path("frontend/index.html")
t = p.read_text(encoding="utf-8")

old1 = """            beginJobUI(
              document.getElementById('transcribeResult'),
              document.getElementById('transcribeBtn'),
              'Upload voorbereiden… (signaal is binnen)',
            );
            await yieldForPaint();
            const contentType = transcribeSelectedFile.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', transcribeSelectedFile.name);
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

            await uploadToSignedUrl(initData.session_url, contentType, transcribeSelectedFile);"""

new1 = """            const transcribeResultEl = document.getElementById('transcribeResult');
            beginJobUI(
              transcribeResultEl,
              document.getElementById('transcribeBtn'),
              'Signaal ontvangen — uploadadres aanvragen…',
            );
            await yieldForPaint();
            let trMsg = transcribeResultEl.querySelector('.progress-msg');
            let trFill = transcribeResultEl.querySelector('.progress-fill');
            let trBar = transcribeResultEl.querySelector('.progress-bar');
            const contentType = transcribeSelectedFile.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', transcribeSelectedFile.name);
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
            if (trMsg) trMsg.textContent = 'Video uploaden naar opslag… (kan bij een grote file enkele minuten duren)';
            await uploadToSignedUrl(initData.session_url, contentType, transcribeSelectedFile, function (loaded, total) {
              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;
              if (trFill) trFill.style.width = pct + '%';
              if (trBar && pct > 0) trBar.classList.remove('progress-bar--waiting');
              if (trMsg) {
                const mb = function (n) { return (n / 1048576).toFixed(1); };
                trMsg.textContent = 'Video uploaden… ' + pct + '% (' + mb(loaded) + ' / ' + mb(total) + ' MB)';
              }
            }, function (state) {
              if (!trMsg) return;
              if (state === 'paused') trMsg.textContent = 'Upload gepauzeerd — opnieuw proberen…';
              if (state === 'resuming') trMsg.textContent = 'Verbinding hersteld — upload hervat…';
            });"""

if old1 not in t:
    raise SystemExit("transcribe block not found len=" + str(len(t.split("Upload voorbereiden"))))
t = t.replace(old1, new1, 1)

old2 = """            beginJobUI(
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

            await uploadToSignedUrl(initData.session_url, contentType, transcribeTextSelectedFile);"""

new2 = """            const transcribeTextResultEl = document.getElementById('transcribeTextResult');
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
            });"""

if old2 not in t:
    raise SystemExit("transcribeText block not found")
t = t.replace(old2, new2, 1)

p.write_text(t, encoding="utf-8")
print("ok")
