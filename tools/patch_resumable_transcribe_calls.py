from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")

t = t.replace(
    """            const putRes = await fetch(initData.upload_url, {
              method: 'PUT',
              headers: { 'Content-Type': contentType },
              body: transcribeSelectedFile,
            });
            if (!putRes.ok) throw new Error('Direct upload to storage failed: ' + putRes.status);""",
    """            await uploadToSignedUrl(initData.session_url, contentType, transcribeSelectedFile);""",
    1,
)

t = t.replace(
    """            const putRes = await fetch(initData.upload_url, {
              method: 'PUT',
              headers: { 'Content-Type': contentType },
              body: transcribeTextSelectedFile,
            });
            if (!putRes.ok) throw new Error('Direct upload to storage failed: ' + putRes.status);""",
    """            await uploadToSignedUrl(initData.session_url, contentType, transcribeTextSelectedFile);""",
    1,
)

p.write_text(t, encoding="utf-8")
print("ok")
