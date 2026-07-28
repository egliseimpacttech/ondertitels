import { useEffect, useState } from 'react';
import { apiBase, apiJson } from '@/lib/api';
import type { LibraryFile, LibraryListing } from '@/types';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';

type Props = {
  open: boolean;
  filterTypes: string[];
  onClose: () => void;
  onSelect: (file: { libraryId: string; name: string }) => void;
};

export function LibPickerModal({ open, filterTypes, onClose, onSelect }: Props) {
  const [path, setPath] = useState('');
  const [data, setData] = useState<LibraryListing | null>(null);
  const [selected, setSelected] = useState<LibraryFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPath('');
    setSelected(null);
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const listing = await apiJson<LibraryListing>(
          `${apiBase}/api/library?path=${encodeURIComponent(path)}`,
        );
        if (!cancelled) setData(listing);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Erreur');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, path]);

  const parts = path ? path.split('/') : [];
  const files = (data?.files || []).filter((f) => {
    if (!filterTypes.length) return true;
    return filterTypes.includes(f.type);
  });

  return (
    <Modal
      open={open}
      title="Choisir un fichier dans la bibliothèque"
      onClose={onClose}
      footer={
        <>
          <Button
            disabled={!selected}
            onClick={() => {
              if (!selected) return;
              onSelect({ libraryId: selected.id, name: selected.name });
              onClose();
            }}
          >
            Sélectionner
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Annuler
          </Button>
        </>
      }
    >
      <div className="breadcrumb">
        <button type="button" onClick={() => setPath('')}>
          Racine
        </button>
        {parts.map((p, i) => {
          const next = parts.slice(0, i + 1).join('/');
          return (
            <span key={next}>
              {' / '}
              <button type="button" onClick={() => setPath(next)}>
                {p}
              </button>
            </span>
          );
        })}
      </div>
      {loading ? <div className="empty-msg">Chargement…</div> : null}
      {error ? <div className="message error">{error}</div> : null}
      <div className="picker-list">
        {(data?.folders || []).map((folder) => (
          <button
            key={folder.id}
            type="button"
            className="picker-item folder"
            onClick={() => {
              setSelected(null);
              setPath(folder.path);
            }}
          >
            📁 {folder.name}
          </button>
        ))}
        {files.map((file) => (
          <button
            key={file.id}
            type="button"
            className={`picker-item ${selected?.id === file.id ? 'selected' : ''}`}
            onClick={() => setSelected(file)}
          >
            {file.type === 'vtt' ? '📄' : file.type === 'text' ? '📝' : file.type === 'audio' ? '🎵' : '🎬'}{' '}
            {file.name}
          </button>
        ))}
        {!loading && !files.length && !(data?.folders || []).length ? (
          <div className="empty-msg">Aucun fichier correspondant.</div>
        ) : null}
      </div>
    </Modal>
  );
}
