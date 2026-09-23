"use client";

import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { AnswerValue } from "@/components/forms/AnswerValue";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { DraftPlayer } from "@/types/draft.types";

const EYEBROW = "text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)]";

/** Public registration answers and the organizer's notes, collapsed under the stats. */
export function RegistrationSection({ player }: Readonly<{ player: DraftPlayer }>) {
  const t = useTranslations("draftRedesign");
  const notes = player.notes?.trim() ? player.notes : null;
  // Every public answer with the field's CURRENT label and kind — no form schema needed here.
  const customFields = player.custom_fields ?? [];

  return (
    <Collapsible className="border-t border-[color:var(--aqt-border)]">
      <CollapsibleTrigger className="group flex min-h-11 w-full items-center gap-2 px-3.5 py-2 text-left outline-none hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]">
        <span className={EYEBROW}>{t("island.registration.heading")}</span>
        <span className="text-xs tabular-nums text-[color:var(--aqt-fg-faint)]">
          {customFields.length + (notes ? 1 : 0)}
        </span>
        <ChevronDown
          className="ml-auto h-4 w-4 text-[color:var(--aqt-fg-muted)] transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 px-3.5 pb-3">
        {notes && (
          <section>
            <h3 className={EYEBROW}>{t("note")}</h3>
            <p className="mt-1 whitespace-pre-line text-sm text-[color:var(--aqt-fg)]">{notes}</p>
          </section>
        )}
        <section>
          <h3 className={EYEBROW}>{t("profile.answersHeading")}</h3>
          {customFields.length === 0 ? (
            <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">{t("profile.noAnswers")}</p>
          ) : (
            <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
              {customFields.map((entry) => (
                <div key={entry.key} className="min-w-0">
                  <dt className="text-xs text-[color:var(--aqt-fg-muted)]">{entry.label}</dt>
                  <dd className="mt-0.5 break-words text-[color:var(--aqt-fg)]">
                    <AnswerValue
                      value={entry.value}
                      kind={entry.type}
                      labels={{ yes: t("customFieldYes"), no: t("customFieldNo") }}
                    />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </CollapsibleContent>
    </Collapsible>
  );
}
