import { useState } from 'react';
import { Video } from 'lucide-react';
import { StudioPageShell } from '@/components/studio/StudioPageShell';
import { FileSourcePicker } from '@/components/ui/FileSourcePicker';
import { Button } from '@/components/ui/Button';
import { JobResult } from '@/components/ui/JobResult';
import { LibPickerModal } from '@/components/library/LibPickerModal';
import { downloadViaApi, isLocalHost } from '@/lib/api';
import { createResumableSession, uploadResumableWithRetry } from '@/lib/gcs';
import { runJob, type JobProgress } from '@/lib/jobs';
import { resolveAsFile } from '@/lib/studio';
import type { FileSource } from '@/types';

type PickerKind = 'video' | 'vtt' | null;

export function StudioBurnPage() {
  const [burnVideo, setBurnVideo] = useState<FileSource | null>(null);
  const [burnVtt, setBurnVtt] = useState<FileSource | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [picker, setPicker] = useState<PickerKind>(null);

  async function handleBurn() {
    if (!burnVideo || !burnVtt) {
      setError('Sélectionnez une vidéo et un fichier VTT.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const inputName = burnVideo.kind === 'local' ? burnVideo.file.name : burnVideo.name;
      const MAX_DIRECT_UPLOAD_MB = 25;
      const videoLarge =
        burnVideo.kind === 'local' &&
        !isLocalHost() &&
        (burnVideo.file.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;

      if (videoLarge && burnVideo.kind === 'local') {
        setProgress({ phase: 'uploading', progress: 1, message: 'Envoi des fichiers…' });
        const videoFile = burnVideo.file;
        const vttFile = await resolveAsFile(burnVtt, 'subs.vtt');
        const vInit = await createResumableSession(videoFile.name, videoFile.type || 'video/mp4');
        await uploadResumableWithRetry(
          vInit.session_url,
          videoFile,
          videoFile.type || 'video/mp4',
          (loaded, total) => {
            const pct = total ? Math.max(1, Math.min(90, Math.round((loaded / total) * 90))) : 1;
            setProgress({ phase: 'uploading', progress: pct, message: `Vidéo… ${pct}%` });
          },
        );
        const sInit = await createResumableSession(vttFile.name, vttFile.type || 'text/vtt');
        await uploadResumableWithRetry(
          sInit.session_url,
          vttFile,
          vttFile.type || 'text/vtt',
          (loaded, total) => {
            const frac = total ? loaded / total : 1;
            const pct = Math.max(91, Math.min(99, 91 + Math.round(frac * 8)));
            setProgress({ phase: 'uploading', progress: pct, message: `Sous-titres… ${pct}%` });
          },
        );
        const gcsForm = new FormData();
        gcsForm.append('video_object_name', vInit.object_name);
        gcsForm.append('vtt_object_name', sInit.object_name);
        await runJob({
          endpoint: '/api/burn-gcs',
          formData: gcsForm,
          downloadName: 'video_with_subtitles.mp4',
          resultUrlSuffix: '_burned.mp4',
          saveMeta: { inputFileName: inputName, librarySuffix: 'burned' },
          onProgress: setProgress,
        });
      } else {
        const fd = new FormData();
        fd.append('video', await resolveAsFile(burnVideo, 'video.mp4'));
        fd.append('vtt', await resolveAsFile(burnVtt, 'subs.vtt'));
        await runJob({
          endpoint: '/api/burn',
          formData: fd,
          downloadName: 'video_with_subtitles.mp4',
          resultUrlSuffix: '_burned.mp4',
          saveMeta: { inputFileName: inputName, librarySuffix: 'burned' },
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
      title="Incrustation dans la vidéo"
      description="Intégrez vos sous-titres VTT dans la vidéo (MP4 gravé)."
      icon={<Video size={18} />}
    >
      <div className="field">
        <span>Fichier vidéo</span>
        <FileSourcePicker
          accept=".mp4,.webm,.mkv"
          source={burnVideo}
          onLocalFile={(f) => setBurnVideo({ kind: 'local', file: f })}
          onOpenLibrary={() => setPicker('video')}
        />
      </div>
      <div className="field">
        <span>Fichier de sous-titres (VTT)</span>
        <FileSourcePicker
          accept=".vtt"
          source={burnVtt}
          onLocalFile={(f) => setBurnVtt({ kind: 'local', file: f })}
          onOpenLibrary={() => setPicker('vtt')}
        />
      </div>
      <div className="form-actions">
        <Button disabled={busy} onClick={() => void handleBurn()}>
          Incruster dans la vidéo
        </Button>
      </div>
      <JobResult
        progress={progress}
        error={error}
        downloadLabel="Télécharger la vidéo"
        onDownload={
          progress?.downloadUrl
            ? () => void downloadViaApi(progress.downloadUrl!, progress.downloadName || 'burned.mp4')
            : undefined
        }
      />
      <LibPickerModal
        open={!!picker}
        filterTypes={picker === 'video' ? ['video'] : ['vtt']}
        onClose={() => setPicker(null)}
        onSelect={(f) => {
          const src: FileSource = { kind: 'library', libraryId: f.libraryId, name: f.name };
          if (picker === 'video') setBurnVideo(src);
          else setBurnVtt(src);
        }}
      />
    </StudioPageShell>
  );
}
