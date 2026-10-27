"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { SearchField } from "@/components/ui/search-field";
import { cn } from "@/lib/utils";

import { MermaidDiagram } from "./MermaidDiagram";
import { PACKAGE_NOTES } from "./schema-notes";
import schema from "./schema.generated.json";

const NOTE = "text-body leading-relaxed text-[color:var(--aqt-fg-muted)]";

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
    <div className="mt-6 flex flex-col gap-3">
      <SearchField
        value={query}
        onValueChange={setQuery}
        label={t("searchLabel")}
        placeholder={t("searchPlaceholder")}
        containerClassName="max-w-sm"
      />
      {packages.length === 0 ? <EmptyNote>{t("empty", { query })}</EmptyNote> : null}
      {packages.map((pkg) => {
        const note = PACKAGE_NOTES[pkg.key];
        const isOpen = open.has(pkg.key);
        return (
          <Card key={pkg.key} asChild className="p-4">
            <section aria-labelledby={`schema-${pkg.key}`}>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
                <CardTitle asChild className="text-ui">
                  <h2 id={`schema-${pkg.key}`}>{note?.title[locale] ?? pkg.key}</h2>
                </CardTitle>
                <span className="text-caption text-[color:var(--aqt-fg-faint)]">
                  {pkg.schemas.join(", ")} · {t("tables", { count: pkg.tables.length })}
                </span>
              </div>
              {note ? <p className={cn("mt-1.5 max-w-3xl", NOTE)}>{note.description[locale]}</p> : null}
              {/* Table names are facts, not chips; a name the search matched turns teal. */}
              <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)]">
                {pkg.tables.map((name) => (
                  <li key={name} className={cn(q && name.includes(q) && "text-[color:var(--aqt-teal)]")}>
                    {name}
                  </li>
                ))}
              </ul>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                aria-expanded={isOpen}
                onClick={() => toggle(pkg.key)}
              >
                {isOpen ? t("hideDiagram") : t("showDiagram")}
              </Button>
              {isOpen ? (
                <>
                  <MermaidDiagram code={pkg.mermaid} diagramKey={pkg.key} />
                  {pkg.unique_keys.length > 0 ? (
                    <>
                      <p className={cn("mt-1.5 max-w-3xl", NOTE)}>{t("uniques")}</p>
                      <ul className="mt-3 list-disc pl-5 text-caption text-[color:var(--aqt-fg-muted)]">
                        {pkg.unique_keys.map((key) => (
                          <li key={`${key.table}:${key.columns.join(",")}`}>
                            <code className="text-[color:var(--aqt-fg)]">{key.table}</code> ({key.columns.join(", ")})
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </>
              ) : null}
            </section>
          </Card>
        );
      })}
    </div>
  );
}
