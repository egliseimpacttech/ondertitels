import { apiBase, apiFetch } from './api';
import { auth } from './firebase';
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
  persistenceKey?: string;
  ownerUid?: string;
  signal?: AbortSignal;
};

const JOB_PROGRESS_EVENT = 'ondertitels:job-progress';
const JOB_PROGRESS_STORAGE_PREFIX = 'ondertitels:job:';
const activeMonitors = new Set<string>();

type JobProgressEventDetail = {
  key: string;
  progress: JobProgress | null;
};

function storageKey(key: string) {
  return JOB_PROGRESS_STORAGE_PREFIX + key;
}

export function readJobProgress(key: string): JobProgress | null {
  try {
    const raw = sessionStorage.getItem(storageKey(key));
    if (!raw) return null;
    const progress = JSON.parse(raw) as JobProgress;
    return ['uploading', 'running', 'done', 'error'].includes(progress.phase)
      ? progress
      : null;
  } catch {
    return null;
  }
}

export function subscribeJobProgress(
  key: string,
  onProgress: (progress: JobProgress | null) => void,
): () => void {
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<JobProgressEventDetail>).detail;
    if (detail?.key === key) onProgress(detail.progress);
  };
  window.addEventListener(JOB_PROGRESS_EVENT, listener);
  return () => window.removeEventListener(JOB_PROGRESS_EVENT, listener);
}

function publishJobProgress(
  key: string | undefined,
  onProgress: (progress: JobProgress) => void,
  progress: JobProgress,
) {
  onProgress(progress);
  if (!key) return;
  try {
    sessionStorage.setItem(storageKey(key), JSON.stringify(progress));
  } catch (error) {
    console.warn('Could not persist background job progress.', error);
  }
  window.dispatchEvent(
    new CustomEvent<JobProgressEventDetail>(JOB_PROGRESS_EVENT, {
      detail: { key, progress },
    }),
  );
}

function clearJobProgress(key: string) {
  try {
    sessionStorage.removeItem(storageKey(key));
  } catch (error) {
    console.warn('Could not clear previous background job progress.', error);
  }
  window.dispatchEvent(
    new CustomEvent<JobProgressEventDetail>(JOB_PROGRESS_EVENT, {
      detail: { key, progress: null },
    }),
  );
}

export function resumeJob(
  key: string,
  ownerUid: string,
  onProgress: (progress: JobProgress) => void,
) {
  const saved = readJobProgress(key);
  if (saved?.phase !== 'running' || !saved.jobId) return;

  void monitorJob({
    jobId: saved.jobId,
    resultUrlSuffix: saved.resultSuffix || '.vtt',
    downloadName: saved.downloadName || 'result.vtt',
    persistenceKey: key,
    ownerUid,
    onProgress,
  }).catch((error) => {
    console.error('Could not resume background job monitoring.', error);
  });
}

type MonitorJobOptions = {
  jobId: string;
  resultUrlSuffix: string;
  downloadName: string;
  persistenceKey?: string;
  ownerUid?: string;
  onProgress: (progress: JobProgress) => void;
  signal?: AbortSignal;
};

async function monitorJob(opts: MonitorJobOptions): Promise<void> {
  const monitorKey = opts.persistenceKey || opts.jobId;
  if (activeMonitors.has(monitorKey)) return;
  activeMonitors.add(monitorKey);

  const statusUrl = `${apiBase}/api/status/${opts.jobId}`;
  let consecutiveErrors = 0;
  let lastProgress = 0;
  const emit = (progress: JobProgress) =>
    publishJobProgress(opts.persistenceKey, opts.onProgress, progress);
  const jobMeta = {
    jobId: opts.jobId,
    downloadName: opts.downloadName,
    resultSuffix: opts.resultUrlSuffix,
  };
  const waitBeforeRetry = (attempt: number) =>
    new Promise((resolve) =>
      setTimeout(resolve, Math.min(30000, 1000 * 2 ** Math.min(attempt - 1, 5))),
    );

  emit({
    phase: 'running',
    progress: lastProgress,
    message: 'Tâche démarrée — attente du statut…',
    ...jobMeta,
  });

  try {
    while (true) {
      if (opts.signal?.aborted) throw new Error('Annulé');
      if (opts.ownerUid && auth.currentUser?.uid !== opts.ownerUid) return;

      let statusRes: Response;
      try {
        statusRes = await apiFetch(statusUrl);
      } catch {
        consecutiveErrors += 1;
        emit({
          phase: 'running',
          progress: lastProgress,
          message: `Connexion interrompue, nouvelle tentative (${consecutiveErrors})…`,
          ...jobMeta,
        });
        await waitBeforeRetry(consecutiveErrors);
        continue;
      }

      if (!statusRes.ok) {
        if (statusRes.status === 401) {
          consecutiveErrors += 1;
          emit({
            phase: 'running',
            progress: lastProgress,
            message: `Session à renouveler — reprise automatique (${consecutiveErrors})…`,
            ...jobMeta,
          });
          await waitBeforeRetry(Math.max(consecutiveErrors, 3));
          continue;
        }
        if (statusRes.status === 404) {
          consecutiveErrors += 1;
          if (consecutiveErrors >= 5) {
            throw new Error('Tâche introuvable. Le serveur a peut-être redémarré. Veuillez réessayer.');
          }
          emit({
            phase: 'running',
            progress: lastProgress,
            message: `Tâche introuvable, nouvelle tentative (${consecutiveErrors})…`,
            ...jobMeta,
          });
          await new Promise((resolve) => setTimeout(resolve, 1000 * consecutiveErrors));
          continue;
        }
        if (statusRes.status !== 429 && statusRes.status < 500) {
          const errorData = (await statusRes.json().catch(() => ({}))) as { detail?: string };
          throw new Error(
            errorData.detail || `Échec du suivi de la tâche : ${statusRes.status}`,
          );
        }
        consecutiveErrors += 1;
        emit({
          phase: 'running',
          progress: lastProgress,
          message: `Serveur indisponible, nouvelle tentative (${consecutiveErrors})…`,
          ...jobMeta,
        });
        await waitBeforeRetry(consecutiveErrors);
        continue;
      }

      let status: JobStatus;
      try {
        status = (await statusRes.json()) as JobStatus;
      } catch {
        consecutiveErrors += 1;
        emit({
          phase: 'running',
          progress: lastProgress,
          message: `Statut illisible, nouvelle tentative (${consecutiveErrors})…`,
          ...jobMeta,
        });
        await waitBeforeRetry(consecutiveErrors);
        continue;
      }

      consecutiveErrors = 0;
      lastProgress = status.progress || 0;
      if (status.done) {
        if (status.error) throw new Error(status.error || status.message || 'Erreur');
        emit({
          phase: 'done',
          progress: lastProgress,
          message: `${lastProgress}% — ${status.message || ''}`,
          warning: status.warning,
          downloadUrl: `${apiBase}/api/result/${opts.jobId}${opts.resultUrlSuffix}`,
          ...jobMeta,
        });
        return;
      }

      emit({
        phase: 'running',
        progress: lastProgress,
        message: `${lastProgress}% — ${status.message || ''}${formatEta(status.eta_seconds)}`,
        warning: status.warning,
        ...jobMeta,
      });
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Erreur pendant le suivi de la tâche.';
    emit({
      phase: 'error',
      progress: lastProgress,
      message,
      ...jobMeta,
    });
    throw error;
  } finally {
    activeMonitors.delete(monitorKey);
  }
}

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

  if (opts.persistenceKey) clearJobProgress(opts.persistenceKey);
  opts.onProgress({
    phase: 'uploading',
    progress: 0,
    message: 'Connexion et envoi du fichier… (les gros fichiers peuvent prendre du temps)',
  });

  await yieldForPaint();

  const res = await apiFetch(`${apiBase}${opts.endpoint}`, { method: 'POST', body: opts.formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText || 'Échec du téléversement');

  const jobId = typeof data.job_id === 'string' ? data.job_id : '';
  if (!jobId) throw new Error('Le serveur n’a pas retourné l’identifiant de la tâche.');

  await monitorJob({
    jobId,
    resultUrlSuffix,
    downloadName: finalDownloadName,
    persistenceKey: opts.persistenceKey,
    ownerUid: opts.ownerUid,
    onProgress: opts.onProgress,
    signal: opts.signal,
  });
}
