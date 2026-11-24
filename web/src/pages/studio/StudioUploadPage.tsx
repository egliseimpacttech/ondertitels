import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { StudioPageShell } from '@/components/studio/StudioPageShell';
import { Button } from '@/components/ui/Button';
import { JobResult } from '@/components/ui/JobResult';
import {
  apiBase,
  apiFetch,
  isLocalHost,
  uploadMultipartWithProgress,
} from '@/lib/api';
import { createResumableSession, uploadResumableWithRetry } from '@/lib/gcs';
import { yieldForPaint } from '@/lib/filenames';
import type { JobProgress } from '@/lib/jobs';

export function StudioUploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleUpload() {
    if (!file) {
      setError('Veuillez d’abord choisir un fichier.');
      return;
    }
    setBusy(true);
    setError(null);
    setProgress({ phase: 'uploading', progress: 0, message: 'Démarrage de l’envoi…' });
    try {
      await yieldForPaint();
      const desiredName = name.trim();
      const MAX_DIRECT_UPLOAD_MB = 25;
      const isLarge = !isLocalHost() && (file.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;

      if (isLarge) {
        setProgress({ phase: 'uploading', progress: 1, message: 'Demande d’URL de stockage…' });
        const contentType = file.type || 'application/octet-stream';
        const initData = await createResumableSession(file.name, contentType);
        await uploadResumableWithRetry(initData.session_url, file, contentType, (loaded, total) => {
          const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;
          setProgress({ phase: 'uploading', progress: pct, message: `Téléversement… ${pct}%` });
        });
        const importForm = new FormData();
        importForm.append('object_name', initData.object_name);
        importForm.append('filename', desiredName || file.name);
        importForm.append('folder', '');
        const importRes = await apiFetch(`${apiBase}/api/library/import-gcs`, {
          method: 'POST',
          body: importForm,
        });
        const data = await importRes.json().catch(() => ({}));
        if (!importRes.ok) throw new Error(data.detail || 'Import échoué');
      } else {
        const formData = new FormData();
        formData.append('file', file, desiredName || file.name);
        formData.append('folder', '');
        await uploadMultipartWithProgress(`${apiBase}/api/library/upload`, formData, (loaded, total) => {
          const pct = total ? Math.round((loaded / total) * 100) : 0;
          setProgress({ phase: 'uploading', progress: pct, message: `Téléversement… ${pct}%` });
        });
      }
      setProgress({ phase: 'done', progress: 100, message: 'Fichier envoyé vers la bibliothèque.' });
      setFile(null);
      setName('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
      setProgress(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <StudioPageShell
      title="Envoyer vers la bibliothèque"
      description="Choisissez un fichier, puis envoyez-le directement dans votre bibliothèque."
      icon={<Upload size={18} />}
    >
      <label className="field">
        <span>Nom de fichier facultatif</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="ex. sermon_01.mp4"
        />
      </label>
      <div className="file-source">
        <input
          ref={inputRef}
          type="file"
          accept=".vtt,.txt,.mp3,.mp4,.wav,.m4a"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setFile(f);
            e.target.value = '';
          }}
        />
        <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()}>
          Choisir un fichier
        </Button>
        <Button disabled={busy} onClick={() => void handleUpload()}>
          Envoyer vers la bibliothèque
        </Button>
        <div className={`file-info ${file ? 'selected' : ''}`}>
          {file ? file.name : 'Aucun fichier sélectionné'}
        </div>
      </div>
      <JobResult progress={progress} error={error} />
    </StudioPageShell>
  );
}
