import { apiFetch, apiBase } from './api';

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function createResumableSession(filename: string, contentType: string) {
  const form = new FormData();
  form.append('filename', filename || 'upload.bin');
  form.append('content_type', contentType || 'application/octet-stream');
  const res = await apiFetch(`${apiBase}/api/gcs/resumable-session`, { method: 'POST', body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Échec d’initialisation de l’envoi : ${res.status}`);
  if (!data.session_url || !data.object_name) throw new Error('Réponse d’initialisation invalide.');
  return data as { session_url: string; object_name: string };
}

async function probeResumableOffset(sessionUrl: string, totalSize: number): Promise<number> {
  const res = await fetch(sessionUrl, {
    method: 'PUT',
    headers: {
      'Content-Length': '0',
      'Content-Range': `bytes */${totalSize}`,
    },
  });
  if (res.status === 308) {
    const range = res.headers.get('Range') || res.headers.get('range') || '';
    const m = /bytes=0-(\d+)/i.exec(range);
    if (m) return Number(m[1]) + 1;
    return 0;
  }
  if (res.ok) return totalSize;
  throw new Error(`Vérification de reprise échouée : ${res.status}`);
}

export async function uploadResumableWithRetry(
  sessionUrl: string,
  body: Blob,
  contentType: string,
  onProgress?: (loaded: number, total: number) => void,
  onState?: (state: 'paused' | 'resuming', retries: number) => void,
): Promise<void> {
  const total = body.size || 0;
  if (!total) throw new Error('La taille du fichier est 0');
  const chunkSize = 8 * 1024 * 1024;
  const maxRetries = 8;
  let offset = 0;
  let retries = 0;

  while (offset < total) {
    const end = Math.min(offset + chunkSize, total);
    const chunk = body.slice(offset, end);
    try {
      const res = await fetch(sessionUrl, {
        method: 'PUT',
        headers: {
          'Content-Type': contentType || 'application/octet-stream',
          'Content-Range': `bytes ${offset}-${end - 1}/${total}`,
        },
        body: chunk,
      });
      if (res.status === 308) {
        const range = res.headers.get('Range') || res.headers.get('range') || '';
        const m = /bytes=0-(\d+)/i.exec(range);
        offset = m ? Number(m[1]) + 1 : end;
        retries = 0;
        onProgress?.(offset, total);
        continue;
      }
      if (res.ok) {
        offset = total;
        onProgress?.(total, total);
        return;
      }
      throw new Error(`Échec du transfert d’un bloc : ${res.status}`);
    } catch {
      retries += 1;
      if (retries > maxRetries) {
        throw new Error('Téléversement en pause trop longtemps. Vérifiez Internet et réessayez.');
      }
      onState?.('paused', retries);
      await sleep(Math.min(30000, 1000 * 2 ** retries));
      try {
        offset = await probeResumableOffset(sessionUrl, total);
        onProgress?.(offset, total);
      } catch {
        /* keep retrying */
      }
      onState?.('resuming', retries);
    }
  }
}
