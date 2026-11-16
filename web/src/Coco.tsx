import { useEffect, useRef, useState, type FormEvent } from 'react'
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

export function doing(lines: CocoLine[], working: boolean) {
  for (const line of [...lines].reverse())
    if (line.who === 'steps') {
      const open = line.steps.find((step) => !step.done)
      if (open) return open.text
      break
    }
  return working ? 'Working on your message' : null
}

export function Talk({
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
    if (!text || working || !onSay) return
    onSay(text)
    field.value = ''
  }
  const status = doing(lines, working)
  return (
    <section className="card chat">
      <header>
        <h1>Coco, your agent</h1>
      </header>
      <div className="thread" ref={thread} aria-live="polite">
        {lines.map((line, index) => {
          if (line.who === 'steps') return <Steps key={index} steps={line.steps} />
          return (
            <p key={index} className={line.who === 'you' ? 'mine' : 'theirs'}>
              <span className="sr">{line.who === 'you' ? 'You: ' : 'Coco: '}</span>
              {line.text}
            </p>
          )
        })}
      </div>
      <div className="composer">
        {status && <p className="small doing">{status}</p>}
        <form className="say" onSubmit={submit}>
          <label htmlFor="say" className="sr">
            Message Coco
          </label>
          <input id="say" name="say" type="text" autoComplete="off" placeholder="Message Coco" />
          <button type="submit" className="send" disabled={working}>
            Send
          </button>
        </form>
        {lines.some((line) => line.who === 'you') && (
          <p className="small">
            <button className="link" onClick={onReset}>
              Start a new request
            </button>
          </p>
        )}
      </div>
    </section>
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

  const reviewed = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (!state) return
    const first = reviewed.current === undefined
    const changed = state.review !== reviewed.current
    reviewed.current = state.review ?? null
    if (!first && changed && state.review && state.check_id) navigate(`/check/${state.check_id}?review=${state.review}`)
  }, [state])

  const stepsOpen = lines.some((line) => line.who === 'steps' && line.steps.some((step) => !step.done))
  const waiting = (Boolean(state?.check_id) && !state?.check_done) || stepsOpen
  useEffect(() => {
    if (!(waiting || state?.busy)) return
    const timer = window.setTimeout(refresh, 1000)
    return () => window.clearTimeout(timer)
  }, [waiting, working, state, lines])

  if (!state) return <section className="card chat"><p className="small">Loading Coco.</p></section>

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
        if (event.type === 'review') navigate(`/check/${event.check_id}?review=${event.store}`)
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
