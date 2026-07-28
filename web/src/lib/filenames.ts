export function libraryNameStemFromInput(inputFileName: string): string {
  if (!inputFileName) return '';
  const base = inputFileName.replace(/^[\\/]+/, '').split(/[/\\]/).pop() || '';
  const dot = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return stem.replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_').replace(/\s+/g, ' ').trim() || '';
}

export function buildProcessedOutputFilename(
  inputFileName: string,
  librarySuffix: string,
  extWithDot: string,
): string {
  const stem = libraryNameStemFromInput(inputFileName);
  const suf = String(librarySuffix || 'output').replace(/[<>:"/\\|?*\x00-\x1f\s]+/g, '_');
  const e = (extWithDot || '.vtt').startsWith('.') ? extWithDot : `.${extWithDot}`;
  return `${stem || 'file'}_${suf}${e}`;
}

export function yieldForPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

export function formatEta(seconds?: number | null): string {
  if (seconds == null || seconds <= 0) return '';
  if (seconds >= 60) return ` (~${Math.ceil(seconds / 60)} min)`;
  return ` (~${seconds} s)`;
}

export function fileSourceLabel(source: { kind: string; file?: File; name?: string } | null): string {
  if (!source) return 'Aucun fichier sélectionné';
  if (source.kind === 'local' && source.file) return source.file.name;
  if (source.kind === 'library') return `📚 ${source.name || 'Bibliothèque'}`;
  return 'Aucun fichier sélectionné';
}
