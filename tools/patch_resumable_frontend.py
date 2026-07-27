from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")

old = """    async function uploadToSignedUrl(uploadUrl, contentType, body, onProgress) {
      const type = contentType || 'application/octet-stream';

      // Preferred: XHR for upload progress.
      try {
        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('PUT', uploadUrl, true);
          xhr.setRequestHeader('Content-Type', type);
          xhr.upload.onprogress = (evt) => {
            if (onProgress && evt.lengthComputable) onProgress(evt.loaded, evt.total);
          };
          xhr.onerror = () => reject(new Error('Upload failed (network error).'));
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve();
            else reject(new Error('Upload failed with status ' + xhr.status));
          };
          xhr.send(body);
        });
        return;
      } catch (_) {
        // Fallback: fetch is sometimes more tolerant in some browser/CORS edge cases.
      }

      const res = await fetch(uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': type },
        body,
      });
      if (!res.ok) throw new Error('Upload failed with status ' + res.status);
      if (onProgress) {
        const total = (body && typeof body.size === 'number') ? body.size : 0;
        onProgress(total || 1, total || 1);
      }
    }
"""

new = """    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    async function createResumableSession(filename, contentType) {
      const form = new FormData();
      form.append('filename', filename || 'upload.bin');
      form.append('content_type', contentType || 'application/octet-stream');
      const res = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || ('Resumable init failed: ' + res.status));
      if (!data.session_url || !data.object_name) throw new Error('Resumable init returned invalid payload.');
      return data;
    }

    async function probeResumableOffset(sessionUrl, totalSize) {
      const res = await fetch(sessionUrl, {
        method: 'PUT',
        headers: {
          'Content-Length': '0',
          'Content-Range': 'bytes */' + totalSize,
        },
      });
      if (res.status === 308) {
        const range = res.headers.get('Range') || res.headers.get('range') || '';
        const m = /bytes=0-(\\d+)/i.exec(range);
        if (m) return Number(m[1]) + 1;
        return 0;
      }
      if (res.ok) return totalSize;
      throw new Error('Resume probe failed: ' + res.status);
    }

    async function uploadResumableWithRetry(sessionUrl, body, contentType, onProgress, onState) {
      const total = (body && typeof body.size === 'number') ? body.size : 0;
      if (!total) throw new Error('File size is 0');
      const chunkSize = 8 * 1024 * 1024;
      const maxRetries = 8;
      let offset = 0;
      let retries = 0;
      while (offset < total) {
        const end = Math.min(offset + chunkSize, total);
        const chunk = body.slice(offset, end);
        try {
          const res = await fetch(sessionUrl, {
            method: 'PUT',
            headers: {
              'Content-Type': contentType || 'application/octet-stream',
              'Content-Range': 'bytes ' + offset + '-' + (end - 1) + '/' + total,
            },
            body: chunk,
          });
          if (res.status === 308) {
            const range = res.headers.get('Range') || res.headers.get('range') || '';
            const m = /bytes=0-(\\d+)/i.exec(range);
            offset = m ? (Number(m[1]) + 1) : end;
            retries = 0;
            if (onProgress) onProgress(offset, total);
            continue;
          }
          if (res.ok) {
            offset = total;
            if (onProgress) onProgress(total, total);
            return;
          }
          throw new Error('Chunk upload failed: ' + res.status);
        } catch (_) {
          retries += 1;
          if (retries > maxRetries) throw new Error('Upload paused too long. Check internet and retry.');
          if (onState) onState('paused', retries);
          await sleep(Math.min(30000, 1000 * (2 ** retries)));
          try {
            offset = await probeResumableOffset(sessionUrl, total);
            if (onProgress) onProgress(offset, total);
          } catch (_) {}
          if (onState) onState('resuming', retries);
        }
      }
    }

    async function uploadToSignedUrl(uploadUrl, contentType, body, onProgress, onState) {
      return uploadResumableWithRetry(uploadUrl, body, contentType, onProgress, onState);
    }
"""

if old not in t:
    raise SystemExit("uploadToSignedUrl block not found")
t = t.replace(old, new, 1)

t = t.replace(
    "const initRes = await apiFetch(apiBase + '/api/gcs/upload-url', { method: 'POST', body: urlForm });",
    "const initRes = await createResumableSession(homeUploadSelectedFile.name, contentType);",
    1,
)
t = t.replace("const initData = await initRes.json().catch(() => ({}));", "const initData = initRes;", 1)
t = t.replace("if (!initRes.ok) throw new Error(initData.detail || ('Signed URL failed: ' + initRes.status));\n\n            await uploadToSignedUrl(initData.upload_url, contentType, homeUploadSelectedFile, (loaded, total) => {\n              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;\n              if (fillEl) fillEl.style.width = pct + '%';\n              if (msgEl) msgEl.textContent = 'Uploading video… ' + pct + '%';\n            });",
              "await uploadToSignedUrl(initData.session_url, contentType, homeUploadSelectedFile, (loaded, total) => {\n              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;\n              if (fillEl) fillEl.style.width = pct + '%';\n              if (msgEl) msgEl.textContent = 'Uploading video… ' + pct + '%';\n            }, (state) => {\n              if (!msgEl) return;\n              if (state === 'paused') msgEl.textContent = 'Internet weg. Upload gepauzeerd, opnieuw proberen…';\n              if (state === 'resuming') msgEl.textContent = 'Verbinding hersteld. Upload hervat…';\n            });", 1)

t = t.replace("/api/gcs/upload-url", "/api/gcs/resumable-session")
t = t.replace("await uploadToSignedUrl(initData.upload_url,", "await uploadToSignedUrl(initData.session_url,")

p.write_text(t, encoding="utf-8")
print("ok")
