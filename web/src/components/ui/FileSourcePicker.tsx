import { useRef } from 'react';
import { Button } from './Button';
import { fileSourceLabel } from '@/lib/filenames';
import type { FileSource } from '@/types';

type Props = {
  accept: string;
  source: FileSource | null;
  onLocalFile: (file: File) => void;
  onOpenLibrary: () => void;
  hideLibrary?: boolean;
};

export function FileSourcePicker({ accept, source, onLocalFile, onOpenLibrary, hideLibrary }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="file-source">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onLocalFile(f);
          e.target.value = '';
        }}
      />
      <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()}>
        Depuis l’ordinateur
      </Button>
      {!hideLibrary ? (
        <Button variant="secondary" size="sm" onClick={onOpenLibrary}>
          Depuis la bibliothèque
        </Button>
      ) : null}
      <div className={`file-info ${source ? 'selected' : ''}`}>{fileSourceLabel(source)}</div>
    </div>
  );
}
