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
  let consecutiveErrors = 0;
  let lastProgress = 0;
  opts.onProgress({
    phase: 'running',
    progress: lastProgress,
    message: 'Tâche démarrée — attente du statut…',
    jobId,
    downloadName: finalDownloadName,
    resultSuffix: resultUrlSuffix,
  });

  while (true) {
    if (opts.signal?.aborted) throw new Error('Annulé');

    let statusRes: Response;
    try {
      statusRes = await apiFetch(statusUrl);
    } catch {
      consecutiveErrors += 1;
      opts.onProgress({
        phase: 'running',
        progress: lastProgress,
        message: `Connexion interrompue, nouvelle tentative (${consecutiveErrors})…`,
        jobId,
        downloadName: finalDownloadName,
        resultSuffix: resultUrlSuffix,
      });
      await new Promise((resolve) => setTimeout(resolve, Math.min(30000, 1000 * 2 ** Math.min(consecutiveErrors - 1, 5))));
      continue;
    }

    if (!statusRes.ok) {
      if (statusRes.status === 404) {
        throw new Error('Tâche introuvable. Le serveur a peut-être redémarré. Veuillez réessayer.');
      }
      if (statusRes.status !== 429 && statusRes.status < 500) {
        throw new Error(`Échec du suivi de la tâche : ${statusRes.status}`);
      }
      consecutiveErrors += 1;
      opts.onProgress({
        phase: 'running',
        progress: lastProgress,
        message: `Serveur indisponible, nouvelle tentative (${consecutiveErrors})…`,
        jobId,
        downloadName: finalDownloadName,
        resultSuffix: resultUrlSuffix,
      });
      await new Promise((resolve) => setTimeout(resolve, Math.min(30000, 1000 * 2 ** Math.min(consecutiveErrors - 1, 5))));
      continue;
    }

    let s: JobStatus;
    try {
      s = (await statusRes.json()) as JobStatus;
    } catch {
      consecutiveErrors += 1;
      opts.onProgress({
        phase: 'running',
        progress: lastProgress,
        message: `Statut illisible, nouvelle tentative (${consecutiveErrors})…`,
        jobId,
        downloadName: finalDownloadName,
        resultSuffix: resultUrlSuffix,
      });
      await new Promise((resolve) => setTimeout(resolve, Math.min(30000, 1000 * 2 ** Math.min(consecutiveErrors - 1, 5))));
      continue;
    }

    consecutiveErrors = 0;
    lastProgress = s.progress || 0;
    opts.onProgress({
      phase: s.done ? (s.error ? 'error' : 'done') : 'running',
      progress: lastProgress,
      message: `${lastProgress}% — ${s.message || ''}${formatEta(s.eta_seconds)}`,
      warning: s.warning,
      jobId,
      downloadUrl: s.done && !s.error ? `${apiBase}/api/result/${jobId}${resultUrlSuffix}` : undefined,
      downloadName: finalDownloadName,
      resultSuffix: resultUrlSuffix,
    });
    if (s.done) {
      if (s.error) throw new Error(s.error || s.message || 'Erreur');
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}
