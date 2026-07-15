"use client";

import { useCallback, useEffect, useRef, type ChangeEventHandler } from "react";

import {
  normalizeParticipantSearch,
  PARTICIPANT_SEARCH_MAX_LENGTH
} from "./participants-url-state";

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/g;

function sanitizeVisibleSearch(value: string): string {
  return value.replace(CONTROL_CHARACTERS, "").slice(0, PARTICIPANT_SEARCH_MAX_LENGTH);
}

function syncVisibleSearch(input: HTMLInputElement | null, value: string): void {
  if (!input || input.value === value) return;
  const isFocused = document.activeElement === input;
  const selectionStart = input.selectionStart;
  const selectionEnd = input.selectionEnd;
  input.value = value;
  if (isFocused && selectionStart !== null && selectionEnd !== null) {
    input.setSelectionRange(
      Math.min(selectionStart, value.length),
      Math.min(selectionEnd, value.length)
    );
  }
}

interface PendingSearch {
  baseUrl: string;
  value: string;
}

interface UseParticipantSearchInputOptions {
  canonicalSearch: string;
  canonicalUrl: string;
  onCommit: (value: string) => void;
  delay?: number;
}

export function useParticipantSearchInput({
  canonicalSearch,
  canonicalUrl,
  onCommit,
  delay = 250
}: UseParticipantSearchInputOptions) {
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<PendingSearch | null>(null);

  const cancelPending = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
    pendingRef.current = null;
  }, []);

  useEffect(() => {
    const pending = pendingRef.current;
    if (pending && pending.baseUrl !== canonicalUrl) cancelPending();

    syncVisibleSearch(inputRef.current, canonicalSearch);
  }, [cancelPending, canonicalSearch, canonicalUrl]);

  useEffect(() => cancelPending, [cancelPending]);

  const onChange = useCallback<ChangeEventHandler<HTMLInputElement>>(
    (event) => {
      const input = event.currentTarget;
      const rawValue = input.value;
      const sanitizedValue = sanitizeVisibleSearch(rawValue);
      if (sanitizedValue !== rawValue) {
        const selectionStart = input.selectionStart ?? rawValue.length;
        const selectionEnd = input.selectionEnd ?? selectionStart;
        const sanitizedStart = sanitizeVisibleSearch(rawValue.slice(0, selectionStart)).length;
        const sanitizedEnd = sanitizeVisibleSearch(rawValue.slice(0, selectionEnd)).length;
        input.value = sanitizedValue;
        input.setSelectionRange(sanitizedStart, sanitizedEnd);
      }

      cancelPending();
      pendingRef.current = { baseUrl: canonicalUrl, value: sanitizedValue };
      timerRef.current = setTimeout(() => {
        const pending = pendingRef.current;
        timerRef.current = null;
        pendingRef.current = null;
        if (pending) {
          const normalizedValue = normalizeParticipantSearch(pending.value);
          syncVisibleSearch(inputRef.current, normalizedValue);
          onCommit(normalizedValue);
        }
      }, delay);
    },
    [cancelPending, canonicalUrl, delay, onCommit]
  );

  return { inputRef, onChange };
}
