export type Sentence = { sentence: string; url: string; label: string; heading?: string }

export type Row = {
  condition: string
  condition_label: string
  question: string
  page_status: string
  page_sentences: Sentence[]
  pages_text: string | null
  date_read: string | null
  read_note: string | null
  assistant_status: string
  assistant_reply: string | null
  reply_time: string | null
  assistant_text: string | null
  status_shown: string
  status_text: string
  counts_toward_meets_all_3: boolean
  contradiction: boolean
  contradiction_text: string | null
}

export type Store = {
  domain: string
  name: string | null
  storefront_url: string | null
  checked: boolean
  progress: { replies_in: boolean; pages_read: boolean } | null
  result: string
  result_text: string
  rows: Row[]
}

export type Offer = {
  product_title: string
  variant_labels: string[]
  price_cents: number
  price_text: string
  price_basis: string
  within_budget: boolean
}

export type CheckStore = Store & { offer: Offer | null }

export type Check = {
  id: number
  saved_on: string | null
  search_text: string | null
  requested_size: string | null
  conditions: string[]
  done: boolean
  price_gap: { text: string } | null
  stores: CheckStore[]
}

export type StoreName = { domain: string; name: string }

async function call<T>(path: string, method = 'GET'): Promise<T> {
  const response = await fetch(`/api${path}`, { method })
  if (!response.ok) throw new Error(`${response.status} on ${path}`)
  return response.json()
}

export const getCheck = (id: string) => call<Check>(`/checks/${id}`)
export const replayCheck = (id: number) => call<{ id: number }>(`/checks/${id}/replay`, 'POST')
export const getStores = () => call<StoreName[]>('/stores')
export const getStore = (domain: string) => call<Store>(`/stores/${encodeURIComponent(domain)}`)

export type CocoLine = { who: 'you' | 'coco'; text: string }
export type Condition = { id: string; label: string; definition: string }
export type CocoState = {
  conditions_confirmed: boolean
  conditions: Condition[]
  lines: CocoLine[]
  check_id: number | null
  check_done: boolean
  busy: boolean
}
export type CocoEvent =
  | { type: 'you'; text: string }
  | { type: 'delta'; text: string }
  | { type: 'line' }
  | { type: 'open'; check_id: number }
  | { type: 'end' }

export const getCoco = () => call<CocoState>('/coco')
export const confirmConditions = () => call<CocoState>('/buyer/conditions', 'POST')
export const resetCoco = () => call<{ ok: boolean }>('/coco/reset', 'POST')

export async function sayToCoco(text: string, onEvent: (event: CocoEvent) => void) {
  const response = await fetch('/api/coco', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!response.ok || !response.body) throw new Error(`${response.status} on /coco`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line))
  }
}
