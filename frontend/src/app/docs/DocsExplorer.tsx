"use client";

import { Fragment, useMemo, useState } from "react";

import {
  ALEMBIC_HEAD,
  changeLog,
  DiagramDomain,
  domainMapMermaid,
  domains,
  DocEntry,
  hubs,
  readingNotes,
  schemaOverview,
  TOTAL_TABLES
} from "./diagrams";
import { MermaidDiagram } from "./MermaidDiagram";
import styles from "./docs.module.css";

const OVERVIEW_KEY = "overview";

/** Extract entity/table identifiers from an erDiagram body, lowercased. */
function extractEntities(mermaid: string): string[] {
  const found = new Set<string>();
  const re = /^\s*([A-Z][A-Z0-9_]*)\s*\{/gm;
  let match: RegExpExecArray | null;
  while ((match = re.exec(mermaid)) !== null) {
    found.add(match[1].toLowerCase());
  }
  return Array.from(found);
}

interface DomainIndex {
  domain: DiagramDomain;
  entities: string[];
  haystack: string;
}

/** Render a string with `backtick`-delimited inline-code spans. */
function RichText({ text }: { text: string }) {
  const parts = text.split("`");
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className={styles.code}>
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        )
      )}
    </>
  );
}

function DefinitionList({ items }: { items: DocEntry[] }) {
  return (
    <div className={styles.defList}>
      {items.map((item) => (
        <div key={item.term} className={styles.defItem}>
          <div className={styles.defTerm}>
            <RichText text={item.term} />
          </div>
          <div className={styles.defBody}>
            <RichText text={item.body} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DocsExplorer() {
  const [selected, setSelected] = useState<string>(OVERVIEW_KEY);
  const [query, setQuery] = useState("");

  const index = useMemo<DomainIndex[]>(
    () =>
      domains.map((domain) => {
        const entities = extractEntities(domain.mermaid);
        const haystack = [
          domain.title,
          domain.schemaLabel,
          domain.description,
          domain.schemas.join(" "),
          entities.join(" ")
        ]
          .join(" ")
          .toLowerCase();
        return { domain, entities, haystack };
      }),
    []
  );

  const normalizedQuery = query.trim().toLowerCase();

  const matches = useMemo(() => {
    if (!normalizedQuery) return index;
    return index.filter((entry) => entry.haystack.includes(normalizedQuery));
  }, [index, normalizedQuery]);

  // Auto-jump to the top match as the user types a table name. Handled in the
  // change event (not an effect) so selection stays in sync without a cascading
  // render — see https://react.dev/learn/you-might-not-need-an-effect.
  const handleQueryChange = (value: string) => {
    setQuery(value);
    const q = value.trim().toLowerCase();
    if (q.length < 2) return;
    const next = index.filter((entry) => entry.haystack.includes(q));
    if (next.length > 0 && !next.some((m) => m.domain.key === selected)) {
      setSelected(next[0].domain.key);
    }
  };

  const activeDomain = domains.find((d) => d.key === selected);

  return (
    <div className={styles.root}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <span className={styles.title}>
            anak-tournaments <span className={styles.accent}>· схема БД</span>
          </span>
          <span className={styles.subtitle}>
            PostgreSQL · {TOTAL_TABLES} таблиц · {schemaOverview.length} схем · alembic head{" "}
            {ALEMBIC_HEAD}
          </span>
        </div>
        <a
          className={styles.topLink}
          href="/docs/design-book.html"
          target="_blank"
          rel="noopener noreferrer"
        >
          Design book →
        </a>
        <div className={styles.search}>
          <span className={styles.searchIcon}>⌕</span>
          <input
            className={styles.searchInput}
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Поиск таблицы или домена…"
            spellCheck={false}
            autoComplete="off"
          />
          {query && (
            <button
              type="button"
              className={styles.searchClear}
              onClick={() => setQuery("")}
              aria-label="Очистить"
            >
              ✕
            </button>
          )}
        </div>
      </header>

      <div className={styles.body}>
        <nav className={styles.sidebar}>
          {!normalizedQuery && (
            <>
              <div className={styles.sidebarHint}>Обзор</div>
              <button
                type="button"
                className={`${styles.navItem} ${
                  selected === OVERVIEW_KEY ? styles.navItemActive : ""
                }`}
                onClick={() => setSelected(OVERVIEW_KEY)}
              >
                <div className={styles.navRow}>
                  <span className={styles.navSection}>§0</span>
                  <span className={styles.navTitle}>Схемы, карта доменов, история</span>
                </div>
              </button>
              <div className={styles.sidebarHint}>Домены</div>
            </>
          )}

          {matches.length === 0 && (
            <div className={styles.navEmpty}>Ничего не найдено по «{query}».</div>
          )}

          {matches.map(({ domain, entities }) => {
            const matchedEntities = normalizedQuery
              ? entities.filter((e) => e.includes(normalizedQuery))
              : [];
            return (
              <button
                key={domain.key}
                type="button"
                className={`${styles.navItem} ${
                  selected === domain.key ? styles.navItemActive : ""
                }`}
                onClick={() => setSelected(domain.key)}
              >
                <div className={styles.navRow}>
                  <span className={styles.navSection}>{domain.section}</span>
                  <span className={styles.navTitle}>{domain.title}</span>
                </div>
                <div className={styles.navMeta}>
                  <span className={styles.navSchema}>{domain.schemaLabel}</span>
                  <span className={styles.navCount}>{domain.tableCount} табл.</span>
                </div>
                {matchedEntities.length > 0 && (
                  <div className={styles.navChips}>
                    {matchedEntities.slice(0, 6).map((e) => (
                      <span key={e} className={`${styles.chip} ${styles.chipMatch}`}>
                        {e}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </nav>

        <main className={styles.stage}>
          {selected === OVERVIEW_KEY || !activeDomain ? (
            <OverviewView onSelectSchema={setSelected} />
          ) : (
            <>
              <div className={styles.stageHeader}>
                <h1 className={styles.stageTitle}>
                  <span className={styles.section}>{activeDomain.section}</span>
                  {activeDomain.title}
                  <span className={styles.stageSchema}>{activeDomain.schemaLabel}</span>
                </h1>
                <p className={styles.stageDesc}>{activeDomain.description}</p>
              </div>
              <MermaidDiagram
                key={activeDomain.key}
                code={activeDomain.mermaid}
                diagramKey={activeDomain.key}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}

/** Map a Postgres schema name to the domain that renders it (for row clicks). */
function domainKeyForSchema(schema: string): string | null {
  const owner = domains.find((d) => d.schemas.includes(schema));
  return owner ? owner.key : null;
}

function OverviewView({ onSelectSchema }: { onSelectSchema: (key: string) => void }) {
  return (
    <div className={styles.overview}>
      <section className={styles.overviewSection}>
        <h2>Postgres-схемы</h2>
        <div className={styles.tableScroll}>
          <table className={styles.schemaTable}>
            <thead>
              <tr>
                <th>Схема</th>
                <th>Домен</th>
                <th>Ключевые таблицы</th>
                <th>Владелец</th>
              </tr>
            </thead>
            <tbody>
              {schemaOverview.map((row) => {
                const key = domainKeyForSchema(row.schema);
                return (
                  <tr
                    key={row.schema}
                    className={key ? styles.schemaRowActive : undefined}
                    onClick={key ? () => onSelectSchema(key) : undefined}
                  >
                    <td>
                      <span className={styles.schemaName}>{row.schema}</span>
                    </td>
                    <td>{row.domain}</td>
                    <td>
                      <span className={styles.schemaKeyTables}>{row.keyTables}</span>
                    </td>
                    <td>
                      <span className={styles.owner}>{row.owner}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.overviewSection}>
        <h2>Общие хабы</h2>
        <DefinitionList items={hubs} />
      </section>

      <section className={styles.overviewSection}>
        <h2>Карта доменов</h2>
        <p className={styles.mapNote}>
          Какие схемы на что ссылаются. Пунктирное ребро — связь «1:0..1» между auth и players.
        </p>
        <div className={styles.mapWrap}>
          <MermaidDiagram code={domainMapMermaid} diagramKey="domain-map" inline />
        </div>
      </section>

      <section className={styles.overviewSection}>
        <h2>История изменений схемы</h2>
        <p className={styles.mapNote}>
          Документ актуализирован под финальное состояние (Alembic head — {ALEMBIC_HEAD}).
        </p>
        <DefinitionList items={changeLog} />
      </section>

      <section className={styles.overviewSection}>
        <h2>Заметки по чтению диаграмм</h2>
        <DefinitionList items={readingNotes} />
      </section>
    </div>
  );
}
