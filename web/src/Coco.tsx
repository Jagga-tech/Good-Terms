import { useEffect, useRef, useState, type FormEvent } from 'react'
import { confirmConditions, getCoco, resetCoco, sayToCoco, type CocoLine, type CocoState } from './api'
import { navigate } from './router'

export function FirstRun({ state, onConfirm }: { state: CocoState; onConfirm?: (zip: string) => void }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const zip = String(new FormData(event.currentTarget).get('zip') ?? '').trim()
    if (/^\d{5}$/.test(zip)) onConfirm?.(zip)
  }
  return (
    <main className="coco">
      <h1>Coco</h1>
      <p className="about">Your personal agent. Tell me once what matters to you, and I keep it.</p>
      <form className="firstrun" onSubmit={submit}>
        <dl className="terms">
          {state.conditions.map((condition) => (
            <div key={condition.id}>
              <dt>{condition.label}</dt>
              <dd>{condition.definition}</dd>
            </div>
          ))}
        </dl>
        <label htmlFor="zip">ZIP code you ship to</label>
        <input id="zip" name="zip" inputMode="numeric" pattern="[0-9]{5}" maxLength={5} defaultValue="94541" required />
        <p className="request">I save these, and every store is asked about your conditions before you see a checkout.</p>
        <button type="submit" className="primary">
          Save my conditions and ZIP
        </button>
      </form>
    </main>
  )
}

export function Talk({
  state,
  lines,
  working,
  onSay,
  onReset,
}: {
  state?: CocoState
  lines: CocoLine[]
  working: boolean
  onSay?: (text: string) => void
  onReset?: () => void
}) {
  const thread = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (thread.current) thread.current.scrollTop = thread.current.scrollHeight
  }, [lines, working])
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const field = event.currentTarget.elements.namedItem('say') as HTMLInputElement
    const text = field.value.trim()
    if (text && onSay) onSay(text)
    field.value = ''
  }
  return (
    <main className="coco">
      <h1>Coco</h1>
      {state && (
        <p className="about">
          Your personal agent. Knows your {state.conditions.length} conditions and ships to {state.zip}.
        </p>
      )}
      <div className="thread" ref={thread}>
        {lines.length === 0 && <p className="plain">What do you need?</p>}
        {lines.map((line, index) => (
          <p key={index} className={`bubble ${line.who === 'you' ? 'mine' : 'theirs'}`}>
            <span className="sr">{line.who === 'you' ? 'You: ' : 'Coco: '}</span>
            {line.text}
          </p>
        ))}
        {working && <p className="working">Coco is working on it.</p>}
      </div>
      <form className="say" onSubmit={submit}>
        <label htmlFor="say" className="sr">
          Tell Coco what you need
        </label>
        <input id="say" name="say" autoComplete="off" placeholder="I need a queen mattress under $400" disabled={working} />
        <button type="submit" className="primary" disabled={working}>
          Send
        </button>
      </form>
      {lines.length > 0 && (
        <p className="saved">
          <button onClick={onReset}>Start a new request</button>
        </p>
      )}
    </main>
  )
}

export default function Coco({ checkShown }: { checkShown?: string | null }) {
  const [state, setState] = useState<CocoState | null>(null)
  const [lines, setLines] = useState<CocoLine[]>([])
  const [working, setWorking] = useState(false)

  const refresh = () =>
    getCoco().then((next) => {
      setState(next)
      setLines(next.lines)
      setWorking(next.busy)
    })

  useEffect(() => {
    refresh()
  }, [])

  useEffect(() => {
    if (state?.check_id && !checkShown) navigate(`/check/${state.check_id}`, true)
  }, [state?.check_id, checkShown])

  const waiting = Boolean(state?.check_id) && !state?.check_done
  const settled = lines.length === (state?.lines.length ?? 0)
  useEffect(() => {
    if (!(waiting || state?.busy) || working) return
    const timer = window.setTimeout(refresh, 2000)
    return () => window.clearTimeout(timer)
  }, [waiting, working, state, settled])

  if (!state) return <main className="coco"><p>Loading Coco.</p></main>
  if (!state.conditions_confirmed) return <FirstRun state={state} onConfirm={(zip) => confirmConditions(zip).then(refresh)} />

  const say = async (text: string) => {
    setWorking(true)
    let open = true
    try {
      await sayToCoco(text, (event) => {
        if (event.type === 'you') setLines((now) => [...now, { who: 'you', text: event.text }])
        if (event.type === 'delta')
          setLines((now) => {
            const last = now[now.length - 1]
            if (open || !last || last.who !== 'coco') return [...now, { who: 'coco', text: event.text }]
            return [...now.slice(0, -1), { who: 'coco', text: last.text + event.text }]
          })
        if (event.type === 'delta') open = false
        if (event.type === 'line') open = true
        if (event.type === 'open') navigate(`/check/${event.check_id}`)
      })
    } finally {
      await refresh()
    }
  }
  const reset = () =>
    resetCoco()
      .then(refresh)
      .then(() => navigate('/'))
  return <Talk state={state} lines={lines} working={working} onSay={say} onReset={reset} />
}
