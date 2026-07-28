import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

export function StudioPageShell({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="page">
      <div className="studio-page-top">
        <Link to="/accueil" className="studio-back">
          <ArrowLeft size={16} /> Accueil
        </Link>
      </div>
      <section className="panel studio-page-panel">
        <div className="panel-head">
          <div className="panel-icon">{icon}</div>
          <div>
            <h1 className="panel-title" style={{ margin: 0 }}>
              {title}
            </h1>
            <p className="panel-desc" style={{ marginBottom: 0 }}>
              {description}
            </p>
          </div>
        </div>
        <div className="studio-page-body">{children}</div>
      </section>
    </div>
  );
}
