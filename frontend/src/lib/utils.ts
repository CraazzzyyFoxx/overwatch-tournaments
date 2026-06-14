import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDateRange(startDate: Date, endDate: Date, locale: string = "ru"): string {
  const start = new Date(startDate);
  const end = new Date(endDate);
  const isRu = locale.startsWith("ru");
  const formatLocale = isRu ? "ru-RU" : "en-US";

  const options: Intl.DateTimeFormatOptions = {
    month: 'short',
    day: 'numeric',
  };

  // Same month: "Jan 15 - 20, 2026" or "15 - 20 янв. 2026 г."
  if (start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()) {
    if (isRu) {
      const monthName = start.toLocaleDateString('ru-RU', { month: 'short' });
      return `${start.getDate()} - ${end.getDate()} ${monthName} ${end.getFullYear()}`;
    }
    const startStr = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return `${startStr} - ${end.getDate()}, ${end.getFullYear()}`;
  }

  // Different months: "Jan 15 - Feb 20, 2026" or "15 янв. - 20 февр. 2026"
  const startStr = start.toLocaleDateString(formatLocale, options);
  const endStr = end.toLocaleDateString(formatLocale, options);
  return `${startStr} - ${endStr}, ${end.getFullYear()}`;
}

export function getStatusColor(isFinished: boolean) {
  return isFinished
    ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
    : "bg-yellow-100 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-100";
}

export function hexToRgba(hex: string, alpha: number): string | null {
  const normalized = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    return null;
  }

  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

