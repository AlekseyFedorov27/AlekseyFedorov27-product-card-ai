import type {
  ProductCard,
  ProductInput,
  ResumeResult,
  StreamEvent,
} from './types'

const API = import.meta.env.VITE_API_URL ?? ''


export class HttpError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'HttpError'
    this.status = status
  }
}


export async function exportMarkdown(card: ProductCard, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`${API}/api/drafts/export/markdown`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(card),
    signal,
  })
  if (!response.ok) {
    const body = await readJsonSafe(response)
    throw new HttpError(response.status, parseFastApiError(body, `HTTP ${response.status}`))
  }
  const data = await response.json() as { markdown: string }
  return data.markdown
}


function parseFastApiError(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback
  const detail = (body as { detail?: unknown }).detail

  if (typeof detail === 'string') return detail

  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d === 'object' && 'msg' in d) {
          const msg = (d as { msg: unknown }).msg
          const loc = (d as { loc?: unknown }).loc
          const field =
            Array.isArray(loc) && loc.length
              ? String(loc[loc.length - 1])
              : null
          return field ? `${field}: ${String(msg)}` : String(msg)
        }
        return null
      })
      .filter((m): m is string => !!m)
    if (messages.length) return messages.join('; ')
  }

  return fallback
}

async function readJsonSafe(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

export async function streamDraft(
  input: ProductInput,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API}/api/drafts/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  })

  if (!response.ok) {
    const body = await readJsonSafe(response)
    const message = parseFastApiError(
      body,
      `Ошибка запроса (HTTP ${response.status})`,
    )
    throw new HttpError(response.status, message)
  }

  if (!response.body) {
    throw new Error('Сервер не вернул поток данных')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''

      for (const chunk of chunks) {
        const dataLine = chunk
          .split('\n')
          .find((l) => l.startsWith('data: '))
        if (!dataLine) continue
        try {
          const parsed = JSON.parse(dataLine.slice(6)) as StreamEvent
          onEvent(parsed)
        } catch (e) {
          onEvent({
            event: 'error',
            message: `Не удалось разобрать событие сервера: ${String(e)}`,
          })
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function resumeDraft(
  threadId: string,
  approved: boolean,
  editedDraft: ProductCard,
  feedback?: string,
  signal?: AbortSignal,
): Promise<ResumeResult> {
  const response = await fetch(`${API}/api/drafts/${threadId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      approved,
      edited_draft: editedDraft,
      feedback: feedback || null,
    }),
    signal,
  })

  if (!response.ok) {
    const body = await readJsonSafe(response)
    const message = parseFastApiError(
      body,
      `Не удалось сохранить решение (HTTP ${response.status})`,
    )
    throw new HttpError(response.status, message)
  }

  return (await response.json()) as ResumeResult
}