import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Mic, MicOff, Radio, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { LangGrid } from '@/components/ui/LangGrid';
import { apiBase, apiFetch, readErrorDetail } from '@/lib/api';
import { TARGET_LANGUAGES } from '@/lib/languages';

type LiveLine = {
  id: string;
  source: string;
  translation: string;
  at: number;
};

type ChunkResult = {
  text?: string;
  translation?: string;
  empty?: boolean;
  asr_provider?: 'local_whisper' | 'huggingface' | 'openai' | 'elevenlabs' | null;
  mt_provider?: 'ollama' | 'nllb' | 'deepl_openai' | 'passthrough' | null;
};

const CHUNK_MS = 5000;
const SOURCE_OPTIONS = [
  { code: 'auto', label: 'Auto' },
  { code: 'fr', label: 'Français' },
  { code: 'nl', label: 'Néerlandais' },
  { code: 'en', label: 'Anglais' },
  ...TARGET_LANGUAGES.filter((l) => !['fr', 'nl', 'en'].includes(l.code)),
];

function pickRecorderMime(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ];
  for (const type of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }
  return '';
}

export function LiveTranslatePage() {
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetLang, setTargetLang] = useState<string[]>(['nl']);
  const [sourceLang, setSourceLang] = useState('fr');
  const [lines, setLines] = useState<LiveLine[]>([]);
  const [partialHint, setPartialHint] = useState('Prêt.');
  const [asrProvider, setAsrProvider] = useState<string | null>(null);
  const [mtProvider, setMtProvider] = useState<string | null>(null);

  const mediaRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const listeningRef = useRef(false);
  const queueRef = useRef<Blob[]>([]);
  const processingRef = useRef(false);
  const targetRef = useRef(targetLang[0] || 'nl');
  const sourceRef = useRef(sourceLang);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    targetRef.current = targetLang[0] || 'nl';
  }, [targetLang]);

  useEffect(() => {
    sourceRef.current = sourceLang;
  }, [sourceLang]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [lines, busy]);

  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    setBusy(true);
    try {
      while (queueRef.current.length) {
        const blob = queueRef.current.shift();
        if (!blob || blob.size < 800) continue;

        setPartialHint('Transcription & traduction…');
        const ext = blob.type.includes('mp4')
          ? 'mp4'
          : blob.type.includes('ogg')
            ? 'ogg'
            : 'webm';
        const fd = new FormData();
        fd.append('audio', blob, `chunk.${ext}`);
        fd.append('target_lang', targetRef.current);
        fd.append('source_lang', sourceRef.current);

        const res = await apiFetch(`${apiBase}/api/live/translate-chunk`, {
          method: 'POST',
          body: fd,
        });
        if (!res.ok) {
          throw new Error(await readErrorDetail(res));
        }
        const data = (await res.json()) as ChunkResult;
        if (data.asr_provider) setAsrProvider(data.asr_provider);
        if (data.mt_provider) setMtProvider(data.mt_provider);
        if (data.empty || !(data.text || '').trim()) {
          setPartialHint(listeningRef.current ? 'À l’écoute…' : 'Prêt.');
          continue;
        }
        setLines((prev) => [
          ...prev,
          {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            source: (data.text || '').trim(),
            translation: (data.translation || data.text || '').trim(),
            at: Date.now(),
          },
        ]);
        setError(null);
        setPartialHint(listeningRef.current ? 'À l’écoute…' : 'Prêt.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur live');
      setPartialHint('Erreur — réessayez.');
    } finally {
      processingRef.current = false;
      setBusy(false);
      if (queueRef.current.length) void processQueue();
    }
  }, []);

  const stopListening = useCallback(() => {
    listeningRef.current = false;
    setListening(false);
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop();
      } catch {
        /* ignore */
      }
    }
    recorderRef.current = null;
    mediaRef.current?.getTracks().forEach((t) => t.stop());
    mediaRef.current = null;
    setPartialHint(queueRef.current.length || processingRef.current ? 'Finalisation…' : 'Arrêté.');
  }, []);

  const startListening = useCallback(async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Micro non disponible dans ce navigateur.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      mediaRef.current = stream;
      const mime = pickRecorderMime();

      const startSegment = () => {
        if (!listeningRef.current || !mediaRef.current) return;
        const rec = mime
          ? new MediaRecorder(mediaRef.current, { mimeType: mime })
          : new MediaRecorder(mediaRef.current);
        const parts: Blob[] = [];

        rec.ondataavailable = (evt) => {
          if (evt.data && evt.data.size > 0) parts.push(evt.data);
        };
        rec.onerror = () => {
          setError('Erreur d’enregistrement micro.');
          stopListening();
        };
        rec.onstop = () => {
          const type = mime || parts[0]?.type || 'audio/webm';
          const blob = new Blob(parts, { type });
          if (blob.size >= 800) {
            // Keep live latency low: only queue the latest chunk if still busy
            if (queueRef.current.length >= 1 || processingRef.current) {
              queueRef.current = [blob];
            } else {
              queueRef.current.push(blob);
            }
            void processQueue();
          }
          // Complete files per segment (timeslice chunks are often invalid WebM alone)
          if (listeningRef.current) {
            window.setTimeout(startSegment, 40);
          }
        };

        recorderRef.current = rec;
        rec.start();
        window.setTimeout(() => {
          if (recorderRef.current === rec && rec.state === 'recording') {
            try {
              rec.stop();
            } catch {
              /* ignore */
            }
          }
        }, CHUNK_MS);
      };

      listeningRef.current = true;
      setListening(true);
      setPartialHint('À l’écoute…');
      startSegment();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Impossible d’accéder au micro. Vérifiez les permissions.',
      );
      setPartialHint('Micro refusé.');
    }
  }, [processQueue, stopListening]);

  useEffect(() => {
    return () => {
      listeningRef.current = false;
      try {
        recorderRef.current?.stop();
      } catch {
        /* ignore */
      }
      mediaRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const targetLabel =
    TARGET_LANGUAGES.find((l) => l.code === targetLang[0])?.label || targetLang[0];

  return (
    <div className="page page--wide">
      <motion.section
        className="hero-band live-hero"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <p className="hero-kicker">Culte en direct</p>
        <h1>Traduction live</h1>
        <p>
          Parlez au micro. ASR local (faster-whisper). Vertaling: DeepL/OpenAI als keys
          aanwezig zijn (snel), anders Ollama.
        </p>
      </motion.section>

      <section className="live-layout">
        <aside className="panel live-controls">
          <div className="panel-head">
            <div className="panel-icon">
              <Radio size={18} />
            </div>
            <div>
              <h2 className="panel-title" style={{ margin: 0 }}>
                Réglages
              </h2>
              <p className="panel-desc" style={{ marginBottom: 0 }}>
                Langue source & cible
              </p>
            </div>
          </div>

          <fieldset>
            <legend>Langue parlée (source)</legend>
            <div className="lang-grid">
              {SOURCE_OPTIONS.map((opt) => (
                <label key={opt.code}>
                  <input
                    type="radio"
                    name="liveSource"
                    checked={sourceLang === opt.code}
                    disabled={listening}
                    onChange={() => setSourceLang(opt.code)}
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Langue de traduction</legend>
            <LangGrid
              selected={targetLang}
              onChange={(codes) => setTargetLang(codes.length ? [codes[codes.length - 1]] : ['nl'])}
              mode="radio"
              name="liveTarget"
            />
          </fieldset>

          <div className="live-mic-row">
            {!listening ? (
              <Button onClick={() => void startListening()}>
                <Mic size={18} /> Démarrer
              </Button>
            ) : (
              <Button variant="danger" onClick={stopListening}>
                <MicOff size={18} /> Arrêter
              </Button>
            )}
            <Button
              variant="secondary"
              disabled={!lines.length && !error}
              onClick={() => {
                setLines([]);
                setError(null);
                setPartialHint(listening ? 'À l’écoute…' : 'Prêt.');
              }}
            >
              <Trash2 size={16} /> Effacer
            </Button>
          </div>

          <div className={`live-status ${listening ? 'live' : ''} ${busy ? 'busy' : ''}`}>
            <span className="live-status-dot" aria-hidden />
            <span>{partialHint}</span>
          </div>
          {error ? <div className="message error">{error}</div> : null}
          <p className="live-note">
            Latence typique 2–6 s. Pour un culte : micro près de la chaire, Français → {targetLabel}.
            {asrProvider || mtProvider
              ? ` ASR : ${
                  asrProvider === 'local_whisper'
                    ? 'faster-whisper (local)'
                    : asrProvider === 'huggingface'
                      ? 'Hugging Face'
                      : asrProvider === 'openai'
                        ? 'OpenAI'
                        : asrProvider === 'elevenlabs'
                          ? 'ElevenLabs'
                          : '—'
                } · MT : ${
                  mtProvider === 'ollama'
                    ? 'Ollama/Qwen'
                    : mtProvider === 'nllb'
                      ? 'NLLB'
                      : mtProvider === 'deepl_openai'
                        ? 'DeepL/OpenAI'
                        : mtProvider || '—'
                }.`
              : ' Setup : pip install faster-whisper + ollama pull qwen2.5:7b'}
          </p>
        </aside>

        <div className="live-stream panel" ref={scrollRef}>
          <div className="live-stream-head">
            <span>Original</span>
            <span>{targetLabel}</span>
          </div>
          {!lines.length ? (
            <div className="live-empty">
              {listening
                ? 'Parlez clairement… les lignes apparaîtront ici.'
                : 'Appuyez sur Démarrer pour commencer la traduction live.'}
            </div>
          ) : (
            <ul className="live-lines">
              {lines.map((line) => (
                <li key={line.id} className="live-line">
                  <p className="live-line-source">{line.source}</p>
                  <p className="live-line-target">{line.translation}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
