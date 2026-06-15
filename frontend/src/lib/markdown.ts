import { marked } from 'marked'

/* Synchronous markdown -> HTML, matching the original app's marked.parse usage. */
export function renderMarkdown(src: string | undefined | null): string {
  if (!src) return ''
  return marked.parse(src, { async: false }) as string
}
