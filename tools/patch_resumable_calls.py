from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")

# Home upload large-file path
t = t.replace(
    "const initRes = await apiFetch(apiBase + '/api/gcs/upload-url', { method: 'POST', body: urlForm });\n            const initData = await initRes.json().catch(() => ({}));\n            if (!initRes.ok) throw new Error(initData.detail || ('Signed URL failed: ' + initRes.status));\n\n            await uploadToSignedUrl(initData.upload_url, contentType, homeUploadSelectedFile, (loaded, total) => {\n              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;\n              if (fillEl) fillEl.style.width = pct + '%';\n              if (msgEl) msgEl.textContent = 'Uploading video… ' + pct + '%';\n            });",
    "const initData = await createResumableSession(homeUploadSelectedFile.name, contentType);\n\n            await uploadToSignedUrl(initData.session_url, contentType, homeUploadSelectedFile, (loaded, total) => {\n              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;\n              if (fillEl) fillEl.style.width = pct + '%';\n              if (msgEl) msgEl.textContent = 'Uploading video… ' + pct + '%';\n            }, (state) => {\n              if (!msgEl) return;\n              if (state === 'paused') msgEl.textContent = 'Internet weg. Upload gepauzeerd, opnieuw proberen…';\n              if (state === 'resuming') msgEl.textContent = 'Verbinding hersteld. Upload hervat…';\n            });",
    1,
)

# Other GCS upload flows: transcribe, transcribe text, burn inputs
t = t.replace("await uploadToSignedUrl(initData.upload_url, contentType, transcribeSelectedFile);", "await uploadToSignedUrl(initData.session_url, contentType, transcribeSelectedFile);")
t = t.replace("await uploadToSignedUrl(initData.upload_url, contentType, transcribeTextSelectedFile);", "await uploadToSignedUrl(initData.session_url, contentType, transcribeTextSelectedFile);")
t = t.replace("await uploadToSignedUrl(vInitData.upload_url, videoType, burnVideoSelected, (loaded, total) => {", "await uploadToSignedUrl(vInitData.session_url, videoType, burnVideoSelected, (loaded, total) => {")
t = t.replace("await uploadToSignedUrl(sInitData.upload_url, vttType, vttBlob, (loaded, total) => {", "await uploadToSignedUrl(sInitData.session_url, vttType, vttBlob, (loaded, total) => {")

# Switch init endpoints to resumable-session where these flows request upload URL
t = t.replace("apiBase + '/api/gcs/upload-url'", "apiBase + '/api/gcs/resumable-session'")

# Keep existing parsing/validation logic intact; endpoint returns session_url + object_name similarly.
p.write_text(t, encoding="utf-8")
print("ok")
