import { TARGET_LANGUAGES } from '@/lib/languages';

type Props = {
  selected: string[];
  onChange: (codes: string[]) => void;
  mode?: 'checkbox' | 'radio';
  name?: string;
};

export function LangGrid({ selected, onChange, mode = 'checkbox', name = 'lang' }: Props) {
  return (
    <div className="lang-grid">
      {TARGET_LANGUAGES.map((lang) => {
        const checked = selected.includes(lang.code);
        return (
          <label key={lang.code}>
            <input
              type={mode}
              name={name}
              value={lang.code}
              checked={checked}
              onChange={() => {
                if (mode === 'radio') {
                  onChange([lang.code]);
                  return;
                }
                onChange(
                  checked ? selected.filter((c) => c !== lang.code) : [...selected, lang.code],
                );
              }}
            />
            {lang.label}
          </label>
        );
      })}
    </div>
  );
}
