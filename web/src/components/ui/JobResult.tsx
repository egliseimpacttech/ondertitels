import type { JobProgress } from '@/lib/jobs';
import { Button } from './Button';

type Props = {
  progress: JobProgress | null;
  error?: string | null;
  onDownload?: () => void;
  onSaveToLibrary?: () => void;
  downloadLabel?: string;
};

export function JobResult({
  progress,
  error,
  onDownload,
  onSaveToLibrary,
  downloadLabel = 'Télécharger',
}: Props) {
  if (error) return <div className="message error">{error}</div>;
  if (!progress) return null;

  if (progress.phase === 'error') {
    return <div className="message error">{progress.message}</div>;
  }

  if (progress.phase === 'done') {
    return (
      <div className="message">
        {progress.warning ? <div className="message error" style={{ marginTop: 0 }}>{progress.warning}</div> : null}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <span>Terminé.</span>
          {onDownload ? (
            <Button size="sm" variant="secondary" onClick={onDownload}>
              {downloadLabel}
            </Button>
          ) : null}
          {onSaveToLibrary ? (
            <Button size="sm" variant="secondary" onClick={onSaveToLibrary}>
              Enregistrer dans la bibliothèque
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-ack">Demande reçue</div>
      <div className="progress-live">
        <span className="spinner" aria-hidden />
        <span>En cours…</span>
      </div>
      <div className={`progress-bar ${progress.progress <= 0 ? 'waiting' : ''}`}>
        <div className="progress-fill" style={{ width: `${Math.max(progress.progress, 0)}%` }} />
      </div>
      <div className="progress-msg">{progress.message}</div>
    </div>
  );
}
