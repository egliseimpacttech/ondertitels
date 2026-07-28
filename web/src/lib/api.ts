import { ensureIdToken } from './firebase';

export const apiBase = '';

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers || {});
  const tok = await ensureIdToken();
  if (tok) headers.set('Authorization', `Bearer ${tok}`);

  let res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    const refreshed = await ensureIdToken(true);
    if (refreshed) {
      headers.set('Authorization', `Bearer ${refreshed}`);
      res = await fetch(url, { ...options, headers });
    }
  }
  return res;
}

export async function readErrorDetail(res: Response): Promise<string> {
  let detail = res.statusText || String(res.status);
  try {
    const body = await res.json();
    if (body?.detail) {
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    }
  } catch {
    /* ignore */
  }
  return detail;
}

export async function apiJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await apiFetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : data?.detail
          ? JSON.stringify(data.detail)
          : res.statusText || String(res.status);
    throw new Error(detail);
  }
  return data as T;
}

export async function downloadViaApi(url: string, filename = ''): Promise<void> {
  const res = await apiFetch(url);
  if (!res.ok) throw new Error(await readErrorDetail(res));
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function fetchLibraryFileBlob(fileId: string): Promise<Blob> {
  const res = await apiFetch(`${apiBase}/api/library/file/${encodeURIComponent(fileId)}`);
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.blob();
}

export function uploadMultipartWithProgress(
  url: string,
  formData: FormData,
  onProgress?: (loaded: number, total: number) => void,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    void (async () => {
      const tok = await ensureIdToken();
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url, true);
      if (tok) xhr.setRequestHeader('Authorization', `Bearer ${tok}`);
      xhr.upload.onprogress = (evt) => {
        if (onProgress && evt.lengthComputable) onProgress(evt.loaded, evt.total);
      };
      xhr.onerror = () => reject(new Error('Échec du téléversement (erreur réseau).'));
      xhr.onload = () => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(xhr.responseText || '{}') as Record<string, unknown>;
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error((data.detail as string) || `Échec du téléversement : ${xhr.status}`));
      };
      xhr.send(formData);
    })();
  });
}

export function isLocalHost(): boolean {
  const host = (window.location.hostname || '').toLowerCase();
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
}
