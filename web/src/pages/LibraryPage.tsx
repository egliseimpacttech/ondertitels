import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import {
  Copy,
  Download,
  Film,
  FolderPlus,
  MoreVertical,
  Pencil,
  Trash2,
  Upload,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import {
  apiBase,
  apiFetch,
  apiJson,
  downloadViaApi,
  fetchLibraryFileBlob,
  uploadMultipartWithProgress,
} from '@/lib/api';
import { ensureIdToken } from '@/lib/firebase';
import { CINEMA_LANG_ROWS } from '@/lib/languages';
import type { CinemaMeta, LibraryFile, LibraryFolder, LibraryListing, VttListItem } from '@/types';
import { VIEW_PATHS } from '@/types';

export function LibraryPage() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [path, setPath] = useState('');
  const [data, setData] = useState<LibraryListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [optionalName, setOptionalName] = useState('');
  const [folderModal, setFolderModal] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [folderEmails, setFolderEmails] = useState('');
  const [videoModal, setVideoModal] = useState<{ id: string; name: string; url: string } | null>(null);
  const [cinemaModal, setCinemaModal] = useState(false);
  const [cinemaFileId, setCinemaFileId] = useState('');
  const [cinemaFileType, setCinemaFileType] = useState('video');
  const [cinemaTitle, setCinemaTitle] = useState('');
  const [cinemaDesc, setCinemaDesc] = useState('');
  const [coverType, setCoverType] = useState<'frame' | 'upload'>('frame');
  const [coverSecond, setCoverSecond] = useState('0');
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [vttOptions, setVttOptions] = useState<VttListItem[]>([]);
  const [subs, setSubs] = useState<Record<string, string>>({});
  const [dragFileId, setDragFileId] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const listing = await apiJson<LibraryListing>(
        `${apiBase}/api/library?path=${encodeURIComponent(path)}`,
      );
      setData(listing);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const close = () => setMenuId(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    for (let i = 0; i < list.length; i++) {
      const file = list[i];
      const fd = new FormData();
      const name = list.length === 1 && optionalName.trim() ? optionalName.trim() : file.name;
      fd.append('file', file, name);
      fd.append('folder', path);
      await uploadMultipartWithProgress(`${apiBase}/api/library/upload`, fd);
    }
    setOptionalName('');
    await load();
  }

  async function createFolder() {
    if (!folderName.trim()) return;
    const fd = new FormData();
    fd.append('name', folderName.trim());
    fd.append('parent', path);
    if (isAdmin && folderEmails.trim()) fd.append('allowed_emails', folderEmails.trim());
    await apiJson(`${apiBase}/api/library/folder`, { method: 'POST', body: fd });
    setFolderModal(false);
    setFolderName('');
    setFolderEmails('');
    await load();
  }

  async function moveFile(fileId: string, targetFolder: string) {
    const fd = new FormData();
    fd.append('folder', targetFolder);
    await apiJson(`${apiBase}/api/library/file/${encodeURIComponent(fileId)}/move`, {
      method: 'POST',
      body: fd,
    });
    await load();
  }

  async function openCinema(file: LibraryFile) {
    if (!['video', 'text', 'audio'].includes(file.type)) {
      alert('Le Cinéma accepte seulement des vidéos, textes et audios.');
      return;
    }
    setCinemaFileId(file.id);
    setCoverFile(null);
    try {
      const meta = await apiJson<CinemaMeta>(`${apiBase}/api/library/file/${file.id}/cinema`);
      setCinemaFileType(meta.file_type || file.type);
      setCinemaTitle(meta.cinema_title || file.name);
      setCinemaDesc(meta.cinema_description || '');
      setCoverType(meta.cinema_cover_type === 'upload' ? 'upload' : 'frame');
      setSubs(meta.cinema_subtitles || {});
      if ((meta.file_type || file.type) === 'video') {
        const vttData = await apiJson<{ items?: VttListItem[]; files?: VttListItem[] }>(
          `${apiBase}/api/library/vtt-list`,
        );
        setVttOptions(vttData.items || vttData.files || []);
      } else {
        setVttOptions([]);
      }
      setCinemaModal(true);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erreur');
    }
  }

  async function saveCinema(publish: boolean) {
    const fd = new FormData();
    fd.append('public', publish ? 'true' : 'false');
    fd.append('title', cinemaTitle);
    fd.append('description', cinemaDesc);
    fd.append('cover_type', coverType);
    fd.append('cover_second', coverSecond);
    fd.append('subtitles_json', JSON.stringify(subs));
    if (coverType === 'upload' && coverFile) fd.append('cover_file', coverFile);
    await uploadMultipartWithProgress(
      `${apiBase}/api/library/file/${cinemaFileId}/cinema`,
      fd,
    );
    setCinemaModal(false);
    alert(publish ? 'Publié sur le Cinéma.' : 'Retiré du Cinéma.');
  }

  async function openItem(file: LibraryFile) {
    if (file.type === 'vtt' || file.type === 'text') {
      const blob = await fetchLibraryFileBlob(file.id);
      const text = await blob.text();
      sessionStorage.setItem(
        'workspace_prefill',
        JSON.stringify({ content: text, filename: file.name }),
      );
      navigate(VIEW_PATHS.workspace);
      return;
    }
    if (file.type === 'video') {
      const tok = await ensureIdToken();
      if (!tok) return;
      setVideoModal({
        id: file.id,
        name: file.name,
        url: `${apiBase}/api/library/file/${encodeURIComponent(file.id)}?token=${encodeURIComponent(tok)}`,
      });
    } else {
      await downloadViaApi(`${apiBase}/api/library/file/${file.id}`, file.name);
    }
  }

  const parts = path ? path.split('/') : [];

  return (
    <div className="page page--wide">
      <h1 style={{ marginTop: 0 }}>Bibliothèque</h1>
      <p style={{ color: 'rgba(12,22,18,0.65)' }}>
        Organisez vos fichiers VTT, audio et vidéo. Glissez un fichier vers un dossier pour le déplacer.
      </p>

      <div className="toolbar">
        <Button variant="secondary" onClick={() => setFolderModal(true)}>
          <FolderPlus size={16} /> Nouveau dossier
        </Button>
        <input
          className="inline-input"
          style={{ minWidth: 260, flex: 1 }}
          value={optionalName}
          onChange={(e) => setOptionalName(e.target.value)}
          placeholder="Nom facultatif pour un seul fichier"
        />
        <input
          ref={uploadRef}
          type="file"
          multiple
          accept=".vtt,.txt,.mp3,.mp4,.wav,.m4a"
          style={{ display: 'none' }}
          onChange={(e) => {
            if (e.target.files) void uploadFiles(e.target.files);
            e.target.value = '';
          }}
        />
        <Button variant="secondary" onClick={() => uploadRef.current?.click()}>
          <Upload size={16} /> Téléverser
        </Button>
      </div>

      <div className="breadcrumb">
        <span
          className={dragFileId ? 'lib-drop' : ''}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (dragFileId) void moveFile(dragFileId, '');
            setDragFileId(null);
          }}
        >
          <button type="button" onClick={() => setPath('')}>
            Racine
          </button>
        </span>
        {parts.map((p, i) => {
          const next = parts.slice(0, i + 1).join('/');
          return (
            <span
              key={next}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragFileId) void moveFile(dragFileId, next);
                setDragFileId(null);
              }}
            >
              {' / '}
              <button type="button" onClick={() => setPath(next)}>
                {p}
              </button>
            </span>
          );
        })}
      </div>

      {error ? <div className="message error">{error}</div> : null}

      <div className="file-list">
        {!data?.folders.length && !data?.files.length ? (
          <div className="empty-msg">Ce dossier est vide.</div>
        ) : null}

        {(data?.folders || []).map((folder) => (
          <FolderRow
            key={folder.id}
            folder={folder}
            menuOpen={menuId === folder.id}
            isAdmin={isAdmin}
            onOpenMenu={(e) => {
              e.stopPropagation();
              setMenuId((id) => (id === folder.id ? null : folder.id));
            }}
            onOpen={() => setPath(folder.path)}
            onDragOver={() => undefined}
            onDrop={() => {
              if (dragFileId) void moveFile(dragFileId, folder.path);
              setDragFileId(null);
            }}
            onDelete={async () => {
              if (!confirm('Supprimer ce dossier ?')) return;
              await apiFetch(`${apiBase}/api/library/folder/${folder.id}`, { method: 'DELETE' });
              await load();
            }}
            onRename={async () => {
              const name = prompt('Nouveau nom du dossier', folder.name);
              if (!name) return;
              const fd = new FormData();
              fd.append('name', name);
              await apiJson(`${apiBase}/api/library/folder/${folder.id}/rename`, {
                method: 'POST',
                body: fd,
              });
              await load();
            }}
            onDuplicate={async () => {
              await apiJson(`${apiBase}/api/library/folder/${folder.id}/duplicate`, { method: 'POST' });
              await load();
            }}
            onPermissions={
              isAdmin
                ? async () => {
                    const emailsStr = prompt(
                      'Adresses e-mail autorisées (séparées par des virgules)',
                      (folder.allowed_emails || []).join(', '),
                    );
                    if (emailsStr === null) return;
                    const fd = new FormData();
                    fd.append('allowed_emails', emailsStr);
                    await apiJson(`${apiBase}/api/library/folder/${folder.id}/permissions`, {
                      method: 'POST',
                      body: fd,
                    });
                    await load();
                  }
                : undefined
            }
          />
        ))}

        {(data?.files || []).map((file) => (
          <FileRow
            key={file.id}
            file={file}
            menuOpen={menuId === file.id}
            dragging={dragFileId === file.id}
            onOpenMenu={(e) => {
              e.stopPropagation();
              setMenuId((id) => (id === file.id ? null : file.id));
            }}
            onDragStart={() => setDragFileId(file.id)}
            onDragEnd={() => setDragFileId(null)}
            onOpen={() => void openItem(file)}
            onDownload={() => void downloadViaApi(`${apiBase}/api/library/file/${file.id}`, file.name)}
            onDelete={async () => {
              if (!confirm('Supprimer ce fichier ?')) return;
              await apiFetch(`${apiBase}/api/library/file/${file.id}`, { method: 'DELETE' });
              await load();
            }}
            onRename={async () => {
              const name = prompt('Nouveau nom', file.name);
              if (!name) return;
              const fd = new FormData();
              fd.append('name', name);
              await apiJson(`${apiBase}/api/library/file/${file.id}/rename`, {
                method: 'POST',
                body: fd,
              });
              await load();
            }}
            onDuplicate={async () => {
              await apiJson(`${apiBase}/api/library/file/${file.id}/duplicate`, { method: 'POST' });
              await load();
            }}
            onCinema={() => void openCinema(file)}
          />
        ))}
      </div>

      <Modal open={folderModal} title="Nouveau dossier" onClose={() => setFolderModal(false)}>
        <label className="field">
          <span>Nom</span>
          <input value={folderName} onChange={(e) => setFolderName(e.target.value)} />
        </label>
        {isAdmin ? (
          <label className="field">
            <span>E-mails autorisés (optionnel)</span>
            <input
              value={folderEmails}
              onChange={(e) => setFolderEmails(e.target.value)}
              placeholder="a@x.com, b@y.com"
            />
          </label>
        ) : null}
        <div className="modal-actions">
          <Button onClick={() => void createFolder()}>Créer</Button>
          <Button variant="secondary" onClick={() => setFolderModal(false)}>
            Annuler
          </Button>
        </div>
      </Modal>

      <Modal
        open={!!videoModal}
        title={videoModal?.name || 'Vidéo'}
        onClose={() => setVideoModal(null)}
        wide
      >
        {videoModal ? (
          <video src={videoModal.url} controls playsInline style={{ width: '100%', maxHeight: '70vh', background: '#000' }} />
        ) : null}
      </Modal>

      <Modal
        open={cinemaModal}
        title="Publier sur le Cinéma"
        onClose={() => setCinemaModal(false)}
        dark
        footer={
          <>
            <Button onClick={() => void saveCinema(true)}>Enregistrer et publier</Button>
            <Button variant="secondary" onClick={() => void saveCinema(false)}>
              Retirer du Cinéma
            </Button>
            <Button variant="secondary" onClick={() => setCinemaModal(false)}>
              Annuler
            </Button>
          </>
        }
      >
        <label className="field">
          <span>Titre</span>
          <input value={cinemaTitle} onChange={(e) => setCinemaTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>Description</span>
          <textarea rows={3} value={cinemaDesc} onChange={(e) => setCinemaDesc(e.target.value)} />
        </label>
        {cinemaFileType === 'video' ? (
          <>
            <label className="field">
              <span>Couverture</span>
              <select
                value={coverType}
                onChange={(e) => setCoverType(e.target.value as 'frame' | 'upload')}
              >
                <option value="frame">Image extraite à la seconde…</option>
                <option value="upload">Téléverser une image</option>
              </select>
            </label>
            {coverType === 'frame' ? (
              <label className="field">
                <span>Seconde</span>
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={coverSecond}
                  onChange={(e) => setCoverSecond(e.target.value)}
                />
              </label>
            ) : (
              <label className="field">
                <span>Image</span>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setCoverFile(e.target.files?.[0] || null)}
                />
              </label>
            )}
            <div className="panel-title" style={{ marginTop: 16, fontSize: '0.95rem' }}>
              Sous-titres (VTT par langue)
            </div>
            {CINEMA_LANG_ROWS.map((lang) => (
              <label key={lang.code} className="field">
                <span>{lang.label}</span>
                <select
                  value={subs[lang.code] || ''}
                  onChange={(e) =>
                    setSubs((prev) => ({ ...prev, [lang.code]: e.target.value }))
                  }
                >
                  <option value="">—</option>
                  {vttOptions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </>
        ) : null}
      </Modal>
    </div>
  );
}

function FolderRow({
  folder,
  menuOpen,
  isAdmin,
  onOpenMenu,
  onOpen,
  onDrop,
  onDelete,
  onRename,
  onDuplicate,
  onPermissions,
}: {
  folder: LibraryFolder;
  menuOpen: boolean;
  isAdmin: boolean;
  onOpenMenu: (e: MouseEvent) => void;
  onOpen: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onDelete: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onPermissions?: () => void;
}) {
  return (
    <div
      className="file-item"
      onDragOver={(e) => {
        e.preventDefault();
        e.currentTarget.classList.add('drag-over');
      }}
      onDragLeave={(e) => e.currentTarget.classList.remove('drag-over')}
      onDrop={(e) => {
        e.preventDefault();
        e.currentTarget.classList.remove('drag-over');
        onDrop();
      }}
    >
      <div className="file-icon">📁</div>
      <div className="file-name" onClick={onOpen}>
        {folder.name}
      </div>
      <div className="file-actions">
        <Button variant="secondary" size="sm" onClick={onOpenMenu}>
          <MoreVertical size={14} />
        </Button>
        {menuOpen ? (
          <div className="menu-dropdown" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="menu-item-btn" onClick={onOpen}>
              Ouvrir
            </button>
            <button type="button" className="menu-item-btn" onClick={onRename}>
              <Pencil size={14} /> Renommer
            </button>
            <button type="button" className="menu-item-btn" onClick={onDuplicate}>
              <Copy size={14} /> Dupliquer
            </button>
            {isAdmin && onPermissions ? (
              <button type="button" className="menu-item-btn" onClick={onPermissions}>
                Permissions
              </button>
            ) : null}
            <button type="button" className="menu-item-btn" onClick={onDelete}>
              <Trash2 size={14} /> Supprimer
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function FileRow({
  file,
  menuOpen,
  dragging,
  onOpenMenu,
  onDragStart,
  onDragEnd,
  onOpen,
  onDownload,
  onDelete,
  onRename,
  onDuplicate,
  onCinema,
}: {
  file: LibraryFile;
  menuOpen: boolean;
  dragging: boolean;
  onOpenMenu: (e: MouseEvent) => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onOpen: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onCinema: () => void;
}) {
  const icon =
    file.type === 'vtt' ? '📄' : file.type === 'text' ? '📝' : file.type === 'audio' ? '🎵' : '🎬';
  return (
    <div
      className={`file-item ${dragging ? 'dragging' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="file-icon">{icon}</div>
      <div className="file-name" onClick={onOpen}>
        {file.name}
      </div>
      <div className="file-actions">
        <Button variant="secondary" size="sm" onClick={onOpenMenu}>
          <MoreVertical size={14} />
        </Button>
        {menuOpen ? (
          <div className="menu-dropdown" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="menu-item-btn" onClick={onOpen}>
              Ouvrir / modifier
            </button>
            <button type="button" className="menu-item-btn" onClick={onCinema}>
              <Film size={14} /> Modifier Cinéma
            </button>
            <button type="button" className="menu-item-btn" onClick={onRename}>
              <Pencil size={14} /> Renommer
            </button>
            <button type="button" className="menu-item-btn" onClick={onDuplicate}>
              <Copy size={14} /> Dupliquer
            </button>
            <button type="button" className="menu-item-btn" onClick={onDownload}>
              <Download size={14} /> Télécharger
            </button>
            <button type="button" className="menu-item-btn" onClick={onDelete}>
              <Trash2 size={14} /> Supprimer
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
