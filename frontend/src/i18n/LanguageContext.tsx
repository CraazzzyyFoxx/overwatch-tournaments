"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import Cookies from "js-cookie";

import { en } from "./locales/en";
import { ru } from "./locales/ru";

export type Locale = "en" | "ru";

interface LanguageContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, variables?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

const translations: Record<Locale, Record<string, any>> = { en, ru };

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ru");

  useEffect(() => {
    const savedLocale = Cookies.get("NEXT_LOCALE") as Locale;
    if (savedLocale === "en" || savedLocale === "ru") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLocaleState(savedLocale);
    } else {
      const browserLang = navigator.language.split("-")[0];
      const defaultLocale: Locale = browserLang === "ru" ? "ru" : "en";
      setLocaleState(defaultLocale);
      Cookies.set("NEXT_LOCALE", defaultLocale, { expires: 365 });
    }
  }, []);

  const setLocale = (newLocale: Locale) => {
    setLocaleState(newLocale);
    Cookies.set("NEXT_LOCALE", newLocale, { expires: 365 });
  };

  const t = (key: string, variables?: Record<string, string | number>): string => {
    const dict = translations[locale] || translations.ru;
    const parts = key.split(".");
    let value: any = dict;

    for (const part of parts) {
      if (value && typeof value === "object" && part in value) {
        value = value[part];
      } else {
        value = undefined;
        break;
      }
    }

    if (typeof value !== "string") {
      // Fallback to English dictionary if key is missing in the current dictionary
      let fallbackValue: any = translations.en;
      for (const part of parts) {
        if (fallbackValue && typeof fallbackValue === "object" && part in fallbackValue) {
          fallbackValue = fallbackValue[part];
        } else {
          fallbackValue = undefined;
          break;
        }
      }
      if (typeof fallbackValue === "string") {
        value = fallbackValue;
      } else {
        return key;
      }
    }

    if (variables) {
      return Object.entries(variables).reduce((str, [k, v]) => {
        return str.replace(new RegExp(`{${k}}`, "g"), String(v));
      }, value);
    }

    return value;
  };

  return (
    <LanguageContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useTranslation must be used within a LanguageProvider");
  }
  return context;
}
