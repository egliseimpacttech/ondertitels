import { useState } from 'react';
import { Mic2 } from 'lucide-react';
import { StudioPageShell } from '@/components/studio/StudioPageShell';
import { FileSourcePicker } from '@/components/ui/FileSourcePicker';
import { Button } from '@/components/ui/Button';
import { JobResult } from '@/components/ui/JobResult';
import { LibPickerModal } from '@/components/library/LibPickerModal';
import { downloadViaApi, isLocalHost } from '@/lib/api';
import { createResumableSession, uploadResumableWithRetry } from '@/lib/gcs';
import { runJob, type JobProgress } from '@/lib/jobs';
import { saveJobToLibrary } from '@/lib/studio';
import type { FileSource } from '@/types';

export function StudioTranscribePage() {
  const [file, setFile] = useState<FileSource | null>(null);
  const [output, setOutput] = useState<'vtt' | 'txt'>('vtt');
  const [isolateVoice, setIsolateVoice] = useState(false);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  async function handleTranscribe() {
    if (!file) {
      setError('Sélectionnez un fichier audio ou vidéo.');
      return;
    }
    setBusy(true);
    setError(null);
    setProgress(null);
    try {
      const isTxt = output === 'txt';
      const inputName = file.kind === 'local' ? file.file.name : file.name;
      const MAX_DIRECT_UPLOAD_MB = 25;
      const localLarge =
        file.kind === 'local' &&
        !isLocalHost() &&
        (file.file.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;

      if (localLarge && file.kind === 'local') {
        setProgress({ phase: 'uploading', progress: 1, message: 'Envoi vers le stockage…' });
        const f = file.file;
        const contentType = f.type || 'application/octet-stream';
        const initData = await createResumableSession(f.name, contentType);
        await uploadResumableWithRetry(initData.session_url, f, contentType, (loaded, total) => {
          const pct = total ? Math.max(1, Math.min(90, Math.round((loaded / total) * 90))) : 1;
          setProgress({ phase: 'uploading', progress: pct, message: `Téléversement… ${pct}%` });
        });
        const gcsForm = new FormData();
        gcsForm.append('object_name', initData.object_name);
        gcsForm.append('isolate_voice', isolateVoice ? '1' : 'false');
        await runJob({
          endpoint: isTxt ? '/api/transcribe-text-gcs' : '/api/transcribe-gcs',
          formData: gcsForm,
          downloadName: isTxt ? 'transcript.txt' : 'transcription.vtt',
          resultUrlSuffix: isTxt ? '.txt' : '.vtt',
          saveMeta: { inputFileName: inputName, librarySuffix: isTxt ? 'transcript' : 'transcription' },
          onProgress: setProgress,
        });
      } else {
        const fd = new FormData();
        if (file.kind === 'local') {
          fd.append('file', file.file);
          fd.append('isolate_voice', isolateVoice ? '1' : 'false');
          await runJob({
            endpoint: isTxt ? '/api/transcribe-text' : '/api/transcribe',
            formData: fd,
            downloadName: isTxt ? 'transcript.txt' : 'transcription.vtt',
            resultUrlSuffix: isTxt ? '.txt' : '.vtt',
            saveMeta: { inputFileName: inputName, librarySuffix: isTxt ? 'transcript' : 'transcription' },
            onProgress: setProgress,
          });
        } else {
          fd.append('file_id', file.libraryId);
          fd.append('isolate_voice', isolateVoice ? '1' : 'false');
          await runJob({
            endpoint: isTxt ? '/api/transcribe-text-library' : '/api/transcribe-library',
            formData: fd,
            downloadName: isTxt ? 'transcript.txt' : 'transcription.vtt',
            resultUrlSuffix: isTxt ? '.txt' : '.vtt',
            saveMeta: { inputFileName: inputName, librarySuffix: isTxt ? 'transcript' : 'transcription' },
            onProgress: setProgress,
          });
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    } finally {
      setBusy(false);
    }
  }

  return (
    <StudioPageShell
      title="Transcription"
      description="Téléversez un fichier audio ou vidéo. Choisissez VTT (horodaté) ou TXT (texte continu)."
      icon={<Mic2 size={18} />}
    >
      <fieldset>
        <legend>Format de sortie</legend>
        <label className="check-row">
          <input type="radio" checked={output === 'vtt'} onChange={() => setOutput('vtt')} />
          Sous-titres (VTT)
        </label>
        <label className="check-row">
          <input type="radio" checked={output === 'txt'} onChange={() => setOutput('txt')} />
          Texte (TXT)
        </label>
      </fieldset>
      <div className="field">
        <span>Fichier audio ou vidéo</span>
        <FileSourcePicker
          accept=".mp4,.mp3,.wav,.m4a"
          source={file}
          onLocalFile={(f) => setFile({ kind: 'local', file: f })}
          onOpenLibrary={() => setPickerOpen(true)}
        />
      </div>
      <label className="check-row" style={{ marginTop: 12 }}>
        <input
          type="checkbox"
          checked={isolateVoice}
          onChange={(e) => setIsolateVoice(e.target.checked)}
        />
        Isolateur de voix (facultatif)
      </label>
      <div className="form-actions">
        <Button disabled={busy} onClick={() => void handleTranscribe()}>
          Lancer la transcription
        </Button>
      </div>
      <JobResult
        progress={progress}
        error={error}
        downloadLabel={output === 'txt' ? 'Télécharger le TXT' : 'Télécharger le VTT'}
        onDownload={
          progress?.downloadUrl
            ? () => void downloadViaApi(progress.downloadUrl!, progress.downloadName || 'result')
            : undefined
        }
        onSaveToLibrary={
          progress?.jobId
            ? () =>
                void saveJobToLibrary(
                  progress.jobId!,
                  progress.downloadName || 'result.vtt',
                  progress.resultSuffix || '.vtt',
                )
            : undefined
        }
      />
      <LibPickerModal
        open={pickerOpen}
        filterTypes={['audio', 'video']}
        onClose={() => setPickerOpen(false)}
        onSelect={(f) => setFile({ kind: 'library', libraryId: f.libraryId, name: f.name })}
      />
    </StudioPageShell>
  );
}
