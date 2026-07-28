import { useEffect, useMemo, useState } from 'react';
import { FileSourcePicker } from '@/components/ui/FileSourcePicker';
import { LibPickerModal } from '@/components/library/LibPickerModal';
import { Button } from '@/components/ui/Button';
import { apiBase, apiFetch, apiJson, fetchLibraryFileBlob } from '@/lib/api';
import { ensureIdToken } from '@/lib/firebase';
import type { FileSource, LibraryListing } from '@/types';

type PickerTarget = 'video' | 'text' | null;

export function WorkspacePage() {
  const [videoSource, setVideoSource] = useState<FileSource | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('subtitles.vtt');
  const [folder, setFolder] = useState('');
  const [folders, setFolders] = useState<{ path: string; name: string }[]>([]);
  const [picker, setPicker] = useState<PickerTarget>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('workspace_prefill');
      if (raw) {
        const parsed = JSON.parse(raw) as { content?: string; filename?: string };
        if (parsed.content != null) setContent(parsed.content);
        if (parsed.filename) setFilename(parsed.filename);
        sessionStorage.removeItem('workspace_prefill');
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const flat: { path: string; name: string }[] = [];
        async function walk(current: string) {
          const listing = await apiJson<LibraryListing>(
            `${apiBase}/api/library?path=${encodeURIComponent(current)}`,
          );
          for (const f of listing.folders) {
            flat.push({ path: f.path, name: f.path });
            await walk(f.path);
          }
        }
        await walk('');
        setFolders(flat);
      } catch {
        /* optional */
      }
    })();
  }, []);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    void (async () => {
      if (!videoSource) {
        setVideoUrl(null);
        return;
      }
      if (videoSource.kind === 'local') {
        objectUrl = URL.createObjectURL(videoSource.file);
        if (!cancelled) setVideoUrl(objectUrl);
        return;
      }
      const tok = await ensureIdToken();
      if (!tok || cancelled) return;
      setVideoUrl(
        `${apiBase}/api/library/file/${encodeURIComponent(videoSource.libraryId)}?token=${encodeURIComponent(tok)}`,
      );
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [videoSource]);

  const vttTrackUrl = useMemo(() => {
    if (!filename.toLowerCase().endsWith('.vtt')) return null;
    const blob = new Blob([content || 'WEBVTT\n\n'], { type: 'text/vtt' });
    return URL.createObjectURL(blob);
  }, [content, filename]);

  useEffect(() => {
    return () => {
      if (vttTrackUrl) URL.revokeObjectURL(vttTrackUrl);
    };
  }, [vttTrackUrl]);

  async function loadTextFromLibrary(id: string, name: string) {
    const blob = await fetchLibraryFileBlob(id);
    const text = await blob.text();
    setContent(text);
    setFilename(name || 'subtitles.vtt');
  }

  async function saveToLibrary() {
    setErr(null);
    setMsg(null);
    try {
      const lower = filename.toLowerCase();
      const blobType = lower.endsWith('.txt') ? 'text/plain' : 'text/vtt';
      const blob = new Blob([content], { type: blobType });
      const formData = new FormData();
      formData.append('file', blob, filename.trim() || 'subtitles.vtt');
      formData.append('folder', folder);
      const res = await apiFetch(`${apiBase}/api/library/upload`, { method: 'POST', body: formData });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Échec : ${res.status}`);
      setMsg(data.overwritten ? 'Enregistré (fichier remplacé).' : 'Enregistré dans la bibliothèque.');
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erreur');
    }
  }

  function downloadLocal() {
    const blob = new Blob([content], {
      type: filename.toLowerCase().endsWith('.txt') ? 'text/plain' : 'text/vtt',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'subtitles.vtt';
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page page--wide">
      <h1 style={{ marginTop: 0 }}>Espace de travail</h1>
      <p style={{ color: 'rgba(12,22,18,0.65)', marginTop: 0 }}>
        Prévisualisez une vidéo avec un VTT éditable. Les modifications mettent à jour l’aperçu automatiquement.
      </p>

      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-title">Vidéo</div>
          <FileSourcePicker
            accept=".mp4,.webm,.mkv"
            source={videoSource}
            onLocalFile={(f) => setVideoSource({ kind: 'local', file: f })}
            onOpenLibrary={() => setPicker('video')}
          />
          <video
            key={`${videoUrl || 'empty'}-${vttTrackUrl || 'no-vtt'}`}
            className="workspace-video"
            controls
            src={videoUrl || undefined}
            style={{ marginTop: 12 }}
          >
            {vttTrackUrl ? <track kind="subtitles" src={vttTrackUrl} srcLang="und" default /> : null}
          </video>
        </section>

        <section className="panel">
          <div className="panel-title">Éditeur</div>
          <div className="toolbar">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = '.vtt,.txt';
                input.onchange = async () => {
                  const f = input.files?.[0];
                  if (!f) return;
                  setContent(await f.text());
                  setFilename(f.name);
                };
                input.click();
              }}
            >
              Depuis l’ordinateur
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setPicker('text')}>
              Depuis la bibliothèque
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setContent('');
                setFilename('subtitles.vtt');
              }}
            >
              Effacer
            </Button>
          </div>
          <label className="field">
            <span>Nom du fichier</span>
            <input value={filename} onChange={(e) => setFilename(e.target.value)} />
          </label>
          <label className="field">
            <span>Dossier cible</span>
            <select value={folder} onChange={(e) => setFolder(e.target.value)}>
              <option value="">Racine</option>
              {folders.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Contenu</span>
            <textarea
              className="workspace-editor"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="WEBVTT…"
            />
          </label>
          <div className="form-actions">
            <Button onClick={downloadLocal}>Télécharger</Button>
            <Button variant="secondary" onClick={() => void saveToLibrary()}>
              Enregistrer dans la bibliothèque
            </Button>
          </div>
          {msg ? <div className="message">{msg}</div> : null}
          {err ? <div className="message error">{err}</div> : null}
        </section>
      </div>

      <LibPickerModal
        open={!!picker}
        filterTypes={picker === 'video' ? ['video'] : ['vtt', 'text']}
        onClose={() => setPicker(null)}
        onSelect={(file) => {
          if (picker === 'video') {
            setVideoSource({ kind: 'library', libraryId: file.libraryId, name: file.name });
          } else {
            void loadTextFromLibrary(file.libraryId, file.name);
          }
        }}
      />
    </div>
  );
}
