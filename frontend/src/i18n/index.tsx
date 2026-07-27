import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { setApiLocale } from "./apiLocale";
import en from "./en";
import { detectLocale, persistLocale, type Locale } from "./localeStorage";
import zh, { type MessageKey } from "./zh-CN";

export type { Locale, MessageKey };

type Vars = Record<string, string | number>;

type I18nValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, vars?: Vars) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

const DICTS: Record<Locale, Record<MessageKey, string>> = {
  "zh-CN": zh,
  en,
};

function format(template: string, vars?: Vars) {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    vars[key] == null ? "" : String(vars[key])
  );
}

export { detectLocale };

export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale || detectLocale);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    persistLocale(next);
    setApiLocale(next);
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
  }, []);

  useEffect(() => {
    setApiLocale(locale);
    document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
  }, [locale]);

  const t = useCallback(
    (key: MessageKey, vars?: Vars) => {
      const dict = DICTS[locale] || zh;
      return format(dict[key] ?? zh[key] ?? key, vars);
    },
    [locale]
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export function useT() {
  return useI18n().t;
}
