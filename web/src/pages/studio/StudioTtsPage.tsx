import { useState } from 'react';
import { FileAudio } from 'lucide-react';
import { StudioPageShell } from '@/components/studio/StudioPageShell';
import { FileSourcePicker } from '@/components/ui/FileSourcePicker';
import { LangGrid } from '@/components/ui/LangGrid';
import { Button } from '@/components/ui/Button';
import { JobResult } from '@/components/ui/JobResult';
import { LibPickerModal } from '@/components/library/LibPickerModal';
import { downloadViaApi } from '@/lib/api';
import { runJob, type JobProgress } from '@/lib/jobs';
import { saveJobToLibrary } from '@/lib/studio';
import type { FileSource } from '@/types';

export function StudioTtsPage() {
  const [file, setFile] = useState<FileSource | null>(null);
  const [ttsLang, setTtsLang] = useState<string[]>(['en']);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  async function handleTts() {
    if (!file) {
      setError('Sélectionnez un fichier TXT ou VTT.');
      return;
    }
    if (!ttsLang[0]) {
      setError('Choisissez une langue audio.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const inputName = file.kind === 'local' ? file.file.name : file.name;
      const fd = new FormData();
      if (file.kind === 'local') {
        fd.append('file', file.file);
        fd.append('languages', ttsLang[0]);
        await runJob({
          endpoint: '/api/tts-generate',
          formData: fd,
          downloadName: 'tts_audio.zip',
          resultUrlSuffix: '_tts.zip',
          saveMeta: { inputFileName: inputName, librarySuffix: 'tts_audio' },
          onProgress: setProgress,
        });
      } else {
        fd.append('file_id', file.libraryId);
        fd.append('languages', ttsLang[0]);
        await runJob({
          endpoint: '/api/tts-generate-library',
          formData: fd,
          downloadName: 'tts_audio.zip',
          resultUrlSuffix: '_tts.zip',
          saveMeta: { inputFileName: inputName, librarySuffix: 'tts_audio' },
          onProgress: setProgress,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    } finally {
      setBusy(false);
    }
  }

  return (
    <StudioPageShell
      title="Voix (TXT / VTT → audio)"
      description="Convertissez un texte en fichiers audio MP3 via ElevenLabs."
      icon={<FileAudio size={18} />}
    >
      <div className="field">
        <span>Fichier TXT ou VTT</span>
        <FileSourcePicker
          accept=".vtt,.txt"
          source={file}
          onLocalFile={(f) => setFile({ kind: 'local', file: f })}
          onOpenLibrary={() => setPickerOpen(true)}
        />
      </div>
      <fieldset>
        <legend>Langue audio (1 seule)</legend>
        <LangGrid selected={ttsLang} onChange={setTtsLang} mode="radio" name="ttsLang" />
      </fieldset>
      <div className="form-actions">
        <Button disabled={busy} onClick={() => void handleTts()}>
          Générer l’audio
        </Button>
      </div>
      <JobResult
        progress={progress}
        error={error}
        downloadLabel="Télécharger les audios (ZIP)"
        onDownload={
          progress?.downloadUrl
            ? () => void downloadViaApi(progress.downloadUrl!, progress.downloadName || 'tts.zip')
            : undefined
        }
        onSaveToLibrary={
          progress?.jobId
            ? () => void saveJobToLibrary(progress.jobId!, 'tts.zip', '_tts.zip')
            : undefined
        }
      />
      <LibPickerModal
        open={pickerOpen}
        filterTypes={['vtt', 'text']}
        onClose={() => setPickerOpen(false)}
        onSelect={(f) => setFile({ kind: 'library', libraryId: f.libraryId, name: f.name })}
      />
    </StudioPageShell>
  );
}
