import { apiBase, apiFetch, fetchLibraryFileBlob } from '@/lib/api';
import type { FileSource } from '@/types';

export async function resolveAsFile(source: FileSource, fieldHint = 'file'): Promise<File> {
  if (source.kind === 'local') return source.file;
  const blob = await fetchLibraryFileBlob(source.libraryId);
  return new File([blob], source.name || fieldHint, { type: blob.type || 'application/octet-stream' });
}

export async function saveJobToLibrary(jobId: string, filename: string, suffix: string) {
  if (suffix === '_tts.zip') {
    const fd = new FormData();
    fd.append('job_id', jobId);
    const res = await apiFetch(`${apiBase}/api/tts-save-to-library`, { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Échec');
    alert('Audios enregistrés dans la bibliothèque.');
    return;
  }
  const res = await apiFetch(`${apiBase}/api/result/${jobId}${suffix}`);
  if (!res.ok) throw new Error('Impossible de récupérer le résultat');
  const blob = await res.blob();
  const formData = new FormData();
  formData.append('file', blob, filename);
  formData.append('folder', '');
  const up = await apiFetch(`${apiBase}/api/library/upload`, { method: 'POST', body: formData });
  if (!up.ok) throw new Error('Échec de l’enregistrement');
  alert('Enregistré dans la bibliothèque.');
}

export const STUDIO_TOOLS = [
  {
    id: 'upload',
    path: '/accueil/envoyer',
    title: 'Envoyer vers la bibliothèque',
    hint: 'Importer un fichier',
    desc: 'Choisissez un fichier et envoyez-le directement dans votre bibliothèque.',
  },
  {
    id: 'transcribe',
    path: '/accueil/transcription',
    title: 'Transcription',
    hint: 'Audio / vidéo → VTT ou TXT',
    desc: 'Transformez un sermon audio ou vidéo en sous-titres horodatés ou texte continu.',
  },
  {
    id: 'translate',
    path: '/accueil/traduire',
    title: 'Traduire',
    hint: 'VTT / TXT multilingue',
    desc: 'Traduisez un fichier VTT ou TXT vers une ou plusieurs langues cibles.',
  },
  {
    id: 'tts',
    path: '/accueil/voix',
    title: 'Voix (TXT / VTT → audio)',
    hint: 'Génération ElevenLabs',
    desc: 'Convertissez un texte en fichiers audio MP3 via ElevenLabs.',
  },
  {
    id: 'burn',
    path: '/accueil/incrustation',
    title: 'Incrustation dans la vidéo',
    hint: 'Graver les sous-titres',
    desc: 'Intégrez vos sous-titres VTT dans la vidéo (MP4 gravé).',
  },
] as const;

export type StudioToolId = (typeof STUDIO_TOOLS)[number]['id'];
