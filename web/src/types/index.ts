export type MediaType = 'vtt' | 'text' | 'audio' | 'video' | string;

export type AppView = 'home' | 'live' | 'cinema' | 'workspace' | 'library' | 'admin';

export type FileSource =
  | { kind: 'local'; file: File }
  | { kind: 'library'; libraryId: string; name: string };

export interface LibraryFolder {
  id: string;
  name: string;
  path: string;
  allowed_emails?: string[];
}

export interface LibraryFile {
  id: string;
  name: string;
  type: MediaType;
  size?: number;
  folder?: string;
}

export interface LibraryListing {
  path: string;
  folders: LibraryFolder[];
  files: LibraryFile[];
}

export interface JobStatus {
  done: boolean;
  progress?: number;
  message?: string;
  error?: string;
  warning?: string;
  eta_seconds?: number | null;
}

export interface CinemaLang {
  code: string;
  name: string;
}

export interface CinemaItem {
  id: string;
  title?: string;
  name?: string;
  description?: string;
  kind?: 'video' | 'ebook' | 'audio' | string;
  cover_url?: string;
  languages?: CinemaLang[];
  updated_at?: number;
}

export interface CinemaCatalog {
  featured?: CinemaItem | null;
  videos?: CinemaItem[];
  ebooks?: CinemaItem[];
  audios?: CinemaItem[];
}

export interface CinemaMeta {
  file_type?: string;
  cinema_title?: string;
  cinema_description?: string;
  cinema_cover_type?: string;
  cinema_subtitles?: Record<string, string>;
  published?: boolean;
}

export interface VttListItem {
  id: string;
  name: string;
  path?: string;
}

export const VIEW_PATHS: Record<AppView, string> = {
  home: '/accueil',
  live: '/traduction-live',
  cinema: '/cinema',
  workspace: '/workspace',
  library: '/bibliotheque',
  admin: '/administration',
};

export const PATH_TO_VIEW: Record<string, AppView> = {
  accueil: 'home',
  'traduction-live': 'live',
  cinema: 'cinema',
  workspace: 'workspace',
  bibliotheque: 'library',
  administration: 'admin',
};
