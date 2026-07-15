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

function isControlCharacter(character: string): boolean {
  const code = character.charCodeAt(0);
  return code <= 0x1f || (code >= 0x7f && code <= 0x9f);
}

function normalizedSelectionOffset(value: string, offset: number, nextLength: number): number {
  const boundedOffset = Math.min(Math.max(offset, 0), value.length);
  let controlFreeOffset = 0;
  for (let index = 0; index < boundedOffset; index += 1) {
    if (!isControlCharacter(value[index])) controlFreeOffset += 1;
  }
  const controlFreeValue = value.replace(CONTROL_CHARACTERS, "");
  const leadingWhitespace = controlFreeValue.length - controlFreeValue.trimStart().length;
  return Math.min(Math.max(controlFreeOffset - leadingWhitespace, 0), nextLength);
}

function syncVisibleSearch(input: HTMLInputElement | null, value: string): void {
  if (!input || input.value === value) return;
  const currentValue = input.value;
  const isFocused = document.activeElement === input;
  const selectionStart = input.selectionStart;
  const selectionEnd = input.selectionEnd;
  const mapsNormalizedValue = normalizeParticipantSearch(currentValue) === value;
  input.value = value;
  if (isFocused && selectionStart !== null && selectionEnd !== null) {
    input.setSelectionRange(
      mapsNormalizedValue
        ? normalizedSelectionOffset(currentValue, selectionStart, value.length)
        : Math.min(selectionStart, value.length),
      mapsNormalizedValue
        ? normalizedSelectionOffset(currentValue, selectionEnd, value.length)
        : Math.min(selectionEnd, value.length)
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
