import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { getCoco, resetCoco, sayToCoco, type CocoLine, type CocoState, type Step } from './api'
import { navigate } from './router'

export function Steps({ steps }: { steps: Step[] }) {
  return (
    <ul className="steps">
      {steps.map((step) => (
        <li key={step.text} className={step.done ? 'done' : 'doing'}>
          <span className="tick" aria-hidden="true">
            {step.done ? '✓' : '·'}
          </span>
          <span>{step.text}</span>
          {!step.done && <span className="sr"> (in progress)</span>}
        </li>
      ))}
    </ul>
  )
}

export function Talk({
  state,
  lines,
  working,
  onSay,
  onReset,
}: {
  state: CocoState
  lines: CocoLine[]
  working: boolean
  onSay?: (text: string) => void
  onReset?: () => void
}) {
  const thread = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState('')
  useEffect(() => {
    if (thread.current) thread.current.scrollTop = thread.current.scrollHeight
  }, [lines, working])
  const send = () => {
    const text = draft.trim()
    if (!text || working || !onSay) return
    onSay(text)
    setDraft('')
  }
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    send()
  }
  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }
  return (
    <main className="coco">
      <div className="agent">
        <h1>Coco</h1>
        <p className="about">Your personal agent</p>
        {state.zip && (
          <p className="memory">
            Remembers: your {state.conditions.length} conditions · ships to {state.zip}
          </p>
        )}
      </div>
      <div className="thread" ref={thread} aria-live="polite">
        {lines.length === 0 && <p className="theirs">What do you need?</p>}
        {lines.map((line, index) => {
          if (line.who === 'steps') return <Steps key={index} steps={line.steps} />
          return (
            <div key={index} className={line.who === 'you' ? 'mine' : 'theirs'}>
              <span className="sr">{line.who === 'you' ? 'You: ' : 'Coco: '}</span>
              {line.text}
            </div>
          )
        })}
      </div>
      <form className="say" onSubmit={submit}>
        <label htmlFor="say" className="sr">
          Message Coco
        </label>
        <textarea
          id="say"
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={keys}
          placeholder="Message Coco"
          disabled={working}
        />
        <button type="submit" className="primary" disabled={working || !draft.trim()}>
          Send
        </button>
      </form>
      {lines.some((line) => line.who === 'you') && (
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

  const stepsOpen = lines.some((line) => line.who === 'steps' && line.steps.some((step) => !step.done))
  const waiting = (Boolean(state?.check_id) && !state?.check_done) || stepsOpen
  useEffect(() => {
    if (!(waiting || state?.busy)) return
    const timer = window.setTimeout(refresh, 1000)
    return () => window.clearTimeout(timer)
  }, [waiting, working, state, lines])

  if (!state) return <main className="coco"><p>Loading Coco.</p></main>

  const say = async (text: string) => {
    setWorking(true)
    let open = true
    try {
      await sayToCoco(text, (event) => {
        if (event.type === 'you') setLines((now) => [...now, { who: 'you', text: event.text }])
        if (event.type === 'steps') getCoco().then((next) => setLines(next.lines))
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
