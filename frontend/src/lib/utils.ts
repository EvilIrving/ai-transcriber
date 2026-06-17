import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 把任意值夹到 0–100 的进度百分比；非数返回 0。 */
export function clampPct(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

/** 翻译并带回退：取不到（或返回的就是 key 本身）时用 fallback。 */
export function translate(t: (key: string) => unknown, key: string, fallback = ''): string {
  if (!key) return fallback
  const value = t(key)
  return typeof value === 'string' && value !== key ? value : fallback
}
