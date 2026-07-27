import { detectLocale, type Locale } from "./localeStorage";

let currentLocale: Locale = detectLocale();

export function getApiLocale(): Locale {
  return currentLocale;
}

export function setApiLocale(locale: Locale) {
  currentLocale = locale;
}

export function localeQuery() {
  return `locale=${encodeURIComponent(currentLocale)}`;
}

export function localeHeaders(extra?: HeadersInit): HeadersInit {
  return {
    "Accept-Language": currentLocale,
    ...(extra || {}),
  };
}
