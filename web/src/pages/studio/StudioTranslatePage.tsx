import { useState } from 'react';
import { Languages } from 'lucide-react';
import { StudioPageShell } from '@/components/studio/StudioPageShell';
import { FileSourcePicker } from '@/components/ui/FileSourcePicker';
import { LangGrid } from '@/components/ui/LangGrid';
import { Button } from '@/components/ui/Button';
import { JobResult } from '@/components/ui/JobResult';
import { LibPickerModal } from '@/components/library/LibPickerModal';
import { downloadViaApi } from '@/lib/api';
import { runJob, type JobProgress } from '@/lib/jobs';
import { resolveAsFile, saveJobToLibrary } from '@/lib/studio';
import type { FileSource } from '@/types';

export function StudioTranslatePage() {
  const [file, setFile] = useState<FileSource | null>(null);
  const [langs, setLangs] = useState<string[]>(['nl', 'en']);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  async function handleTranslate() {
    if (!file) {
      setError('Sélectionnez un fichier VTT ou TXT.');
      return;
    }
    if (!langs.length) {
      setError('Choisissez au moins une langue.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const inputName = file.kind === 'local' ? file.file.name : file.name;
      const isTxt = inputName.toLowerCase().endsWith('.txt');
      const fd = new FormData();
      fd.append('file', await resolveAsFile(file));
      fd.append('languages', langs.join(','));
      await runJob({
        endpoint: '/api/translate',
        formData: fd,
        downloadName: isTxt ? 'translated.txt' : 'translated.vtt',
        resultUrlSuffix: isTxt ? '.txt' : '.vtt',
        saveMeta: { inputFileName: inputName, librarySuffix: 'translated' },
        onProgress: setProgress,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    } finally {
      setBusy(false);
    }
  }

  return (
    <StudioPageShell
      title="Traduire"
      description="Téléversez un VTT ou TXT et choisissez les langues cibles."
      icon={<Languages size={18} />}
    >
      <div className="field">
        <span>Fichier VTT ou TXT</span>
        <FileSourcePicker
          accept=".vtt,.txt"
          source={file}
          onLocalFile={(f) => setFile({ kind: 'local', file: f })}
          onOpenLibrary={() => setPickerOpen(true)}
        />
      </div>
      <fieldset>
        <legend>Langues cibles</legend>
        <LangGrid selected={langs} onChange={setLangs} />
      </fieldset>
      <div className="form-actions">
        <Button disabled={busy} onClick={() => void handleTranslate()}>
          Traduire
        </Button>
      </div>
      <JobResult
        progress={progress}
        error={error}
        onDownload={
          progress?.downloadUrl
            ? () =>
                void downloadViaApi(progress.downloadUrl!, progress.downloadName || 'translated.vtt')
            : undefined
        }
        onSaveToLibrary={
          progress?.jobId
            ? () =>
                void saveJobToLibrary(
                  progress.jobId!,
                  progress.downloadName || 'translated.vtt',
                  progress.resultSuffix || '.vtt',
                )
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
