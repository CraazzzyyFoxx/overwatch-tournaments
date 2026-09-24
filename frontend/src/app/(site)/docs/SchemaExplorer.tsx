"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { SearchField } from "@/components/ui/search-field";
import { cn } from "@/lib/utils";

import { MermaidDiagram } from "./MermaidDiagram";
import { PACKAGE_NOTES } from "./schema-notes";
import schema from "./schema.generated.json";
import styles from "./docs.module.css";

// Reading order is the notes' order (identity and tenancy first, infrastructure
// last); a package the notes do not know yet goes to the end.
const ORDER = Object.keys(PACKAGE_NOTES);
const rank = (key: string) => (ORDER.includes(key) ? ORDER.indexOf(key) : ORDER.length);
const PACKAGES = [...schema.packages].sort((a, b) => rank(a.key) - rank(b.key));

export function SchemaExplorer() {
  const t = useTranslations("docs.schema");
  const locale = useLocale() === "en" ? "en" : "ru";
  const [query, setQuery] = useState("");
  // Diagrams render only while open: all of them at once is seconds of layout.
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const q = query.trim().toLowerCase();

  const packages = PACKAGES.filter(
    (pkg) =>
      !q ||
      pkg.key.includes(q) ||
      pkg.schemas.some((s) => s.includes(q)) ||
      pkg.tables.some((name) => name.includes(q)),
  );

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <div className={styles.schema}>
      <SearchField
        value={query}
        onValueChange={setQuery}
        label={t("searchLabel")}
        placeholder={t("searchPlaceholder")}
        containerClassName={styles.search}
      />
      {packages.length === 0 ? <p className={styles.empty}>{t("empty", { query })}</p> : null}
      {packages.map((pkg) => {
        const note = PACKAGE_NOTES[pkg.key];
        const isOpen = open.has(pkg.key);
        return (
          <section key={pkg.key} className={styles.pkg} aria-labelledby={`schema-${pkg.key}`}>
            <div className={styles.pkgHead}>
              <h2 id={`schema-${pkg.key}`} className={styles.pkgTitle}>
                {note?.title[locale] ?? pkg.key}
              </h2>
              <span className={styles.pkgMeta}>
                {pkg.schemas.join(", ")} · {t("tables", { count: pkg.tables.length })}
              </span>
            </div>
            {note ? <p className={styles.pkgDesc}>{note.description[locale]}</p> : null}
            <ul className={styles.chips}>
              {pkg.tables.map((name) => (
                <li key={name} className={cn(styles.chip, q && name.includes(q) && styles.chipMatch)}>
                  {name}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className={styles.toggle}
              aria-expanded={isOpen}
              onClick={() => toggle(pkg.key)}
            >
              {isOpen ? t("hideDiagram") : t("showDiagram")}
            </button>
            {isOpen ? (
              <>
                <MermaidDiagram code={pkg.mermaid} diagramKey={pkg.key} />
                {pkg.unique_keys.length > 0 ? (
                  <>
                    <p className={styles.pkgDesc}>{t("uniques")}</p>
                    <ul className={styles.uniques}>
                      {pkg.unique_keys.map((key) => (
                        <li key={`${key.table}:${key.columns.join(",")}`}>
                          <code>{key.table}</code> ({key.columns.join(", ")})
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
