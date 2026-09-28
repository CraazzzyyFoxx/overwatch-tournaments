"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle, Info } from "lucide-react";

import type { PickBanRulesIssue } from "@/types/tournament.types";

/**
 * Validator issues, next to the phase or step they name.
 *
 * The engine returns a `code` and an English `message`; the code is translated
 * where a translation exists and the message is the fallback — a new engine
 * rule surfaces its own words rather than nothing while the translation
 * catches up.
 *
 * The translation is per CODE, so several issues of one code collapse into the
 * same sentence: `group_nearly_exhausted` is raised once per role and the
 * translated line cannot say which role. Wherever a code repeats, the server's
 * own message rides along underneath — it is the only place the detail exists.
 */
export function IssueList({ issues }: Readonly<{ issues: PickBanRulesIssue[] }>) {
  const t = useTranslations("pickBan.rules");

  if (issues.length === 0) return null;

  const perCode: Record<string, number> = {};
  for (const issue of issues) perCode[issue.code] = (perCode[issue.code] ?? 0) + 1;

  return (
    <ul className="mt-1.5 flex flex-col gap-1">
      {issues.map((issue, index) => {
        const key = `issue.${issue.code}` as "issue.unknown_leaf";
        const translated = t.has(key);
        const error = issue.severity === "error";
        // `path` and `code` both repeat, so neither identifies a row; the
        // list is rebuilt wholesale on every verdict, so its order does.
        return (
          <li
            key={`${index}-${issue.path}-${issue.code}`}
            className={`flex items-start gap-1.5 text-xs ${error ? "text-destructive" : "text-muted-foreground"}`}
          >
            {error ? (
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            ) : (
              <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            )}
            <span>
              {translated ? t(key) : issue.message}
              {translated && perCode[issue.code] > 1 ? (
                <span className="ms-1 opacity-80">{issue.message}</span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
