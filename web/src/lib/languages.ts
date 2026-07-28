export interface LangOption {
  code: string;
  label: string;
}

export const TARGET_LANGUAGES: LangOption[] = [
  { code: 'nl', label: 'Néerlandais' },
  { code: 'en', label: 'Anglais' },
  { code: 'es', label: 'Espagnol' },
  { code: 'fr', label: 'Français' },
  { code: 'mg', label: 'Malgache' },
  { code: 'kg', label: 'Kikongo' },
  { code: 'ts', label: 'Tshiluba' },
  { code: 'ln', label: 'Lingala' },
  { code: 'pt', label: 'Portugais' },
  { code: 'zh', label: 'Chinois' },
  { code: 'sw', label: 'Swahili' },
];

export const CINEMA_LANG_ROWS = TARGET_LANGUAGES;
