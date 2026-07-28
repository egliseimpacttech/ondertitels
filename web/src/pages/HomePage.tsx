import { Link } from 'react-router-dom';
import { FileAudio, Languages, Mic2, Upload, Video } from 'lucide-react';
import { motion } from 'framer-motion';
import { STUDIO_TOOLS } from '@/lib/studio';

const ICONS = {
  upload: Upload,
  transcribe: Mic2,
  translate: Languages,
  tts: FileAudio,
  burn: Video,
} as const;

export function HomePage() {
  return (
    <div className="page">
      <motion.section
        className="hero-band"
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
      >
        <p className="hero-kicker">Studio</p>
        <h1>Accueil</h1>
        <p>
          Choisissez un outil pour transcrire, traduire, générer la voix ou incruster les
          sous-titres.
        </p>
      </motion.section>

      <section className="studio-hub" aria-label="Outils du studio">
        {STUDIO_TOOLS.map((tool, i) => {
          const Icon = ICONS[tool.id];
          return (
            <motion.div
              key={tool.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: 0.05 * i }}
            >
              <Link to={tool.path} className="studio-hub-card">
                <span className="studio-hub-icon">
                  <Icon size={20} strokeWidth={2.2} />
                </span>
                <span className="studio-hub-text">
                  <span className="studio-hub-title">{tool.title}</span>
                  <span className="studio-hub-hint">{tool.hint}</span>
                  <span className="studio-hub-desc">{tool.desc}</span>
                </span>
              </Link>
            </motion.div>
          );
        })}
      </section>
    </div>
  );
}
