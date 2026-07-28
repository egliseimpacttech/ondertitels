import type { ReactNode } from 'react';
import { Button } from './Button';

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  dark?: boolean;
  wide?: boolean;
  footer?: ReactNode;
};

export function Modal({ open, title, onClose, children, dark, wide, footer }: Props) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal ${dark ? 'dark' : ''}`}
        style={wide ? { width: 'min(720px, 100%)' } : undefined}
        role="dialog"
        aria-modal
        aria-label={title}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'start' }}>
          <h3 style={{ margin: 0 }}>{title}</h3>
          <Button variant="secondary" size="sm" onClick={onClose} aria-label="Fermer">
            ✕
          </Button>
        </div>
        <div style={{ marginTop: 14 }}>{children}</div>
        {footer ? <div className="modal-actions">{footer}</div> : null}
      </div>
    </div>
  );
}
