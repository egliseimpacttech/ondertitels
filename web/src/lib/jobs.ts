import { apiBase, apiFetch } from './api';
import type { JobStatus } from '@/types';
import { buildProcessedOutputFilename, formatEta, yieldForPaint } from './filenames';

export type JobProgress = {
  phase: 'uploading' | 'running' | 'done' | 'error';
  progress: number;
  message: string;
  warning?: string;
  jobId?: string;
  downloadUrl?: string;
  downloadName?: string;
  resultSuffix?: string;
};

export type RunJobOptions = {
  endpoint: string;
  formData: FormData;
  downloadName: string;
  resultUrlSuffix?: string;
  saveMeta?: { inputFileName: string; librarySuffix: string };
  onProgress: (p: JobProgress) => void;
  signal?: AbortSignal;
};

export async function runJob(opts: RunJobOptions): Promise<void> {
  const resultUrlSuffix = opts.resultUrlSuffix || '.vtt';
  let extForName = '.vtt';
  if (resultUrlSuffix === '.txt') extForName = '.txt';
  else if (resultUrlSuffix === '_burned.mp4') extForName = '.mp4';
  else if (resultUrlSuffix === '_tts.zip') extForName = '.zip';

  const finalDownloadName =
    opts.saveMeta?.inputFileName && opts.saveMeta.librarySuffix
      ? buildProcessedOutputFilename(opts.saveMeta.inputFileName, opts.saveMeta.librarySuffix, extForName)
      : opts.downloadName;

  opts.onProgress({
    phase: 'uploading',
    progress: 0,
    message: 'Connexion et envoi du fichier… (les gros fichiers peuvent prendre du temps)',
  });

  await yieldForPaint();

  const res = await apiFetch(`${apiBase}${opts.endpoint}`, { method: 'POST', body: opts.formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText || 'Échec du téléversement');

  const jobId = data.job_id as string;
  const statusUrl = `${apiBase}/api/status/${jobId}`;
  let statusPollErrors = 0;

  await new Promise<void>((resolve, reject) => {
    const tick = async () => {
      if (opts.signal?.aborted) {
        clearInterval(intervalId);
        reject(new Error('Annulé'));
        return;
      }
      try {
        const statusRes = await apiFetch(statusUrl);
        if (!statusRes.ok) {
          clearInterval(intervalId);
          reject(new Error('Tâche introuvable. Le serveur a peut-être redémarré. Veuillez réessayer.'));
          return;
        }
        statusPollErrors = 0;
        const s = (await statusRes.json()) as JobStatus;
        opts.onProgress({
          phase: s.done ? (s.error ? 'error' : 'done') : 'running',
          progress: s.progress || 0,
          message: `${s.progress || 0}% — ${s.message || ''}${formatEta(s.eta_seconds)}`,
          warning: s.warning,
          jobId,
          downloadUrl: s.done && !s.error ? `${apiBase}/api/result/${jobId}${resultUrlSuffix}` : undefined,
          downloadName: finalDownloadName,
          resultSuffix: resultUrlSuffix,
        });
        if (s.done) {
          clearInterval(intervalId);
          if (s.error) reject(new Error(s.error || s.message || 'Erreur'));
          else resolve();
        }
      } catch (err) {
        statusPollErrors += 1;
        if (statusPollErrors >= 5) {
          clearInterval(intervalId);
          reject(err instanceof Error ? err : new Error('Connexion perdue pendant le suivi.'));
        }
      }
    };
    void tick();
    const intervalId = setInterval(() => void tick(), 1000);
  });
}
