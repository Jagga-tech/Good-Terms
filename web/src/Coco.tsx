import { useEffect, useState, type FormEvent } from 'react'
import { confirmConditions, getCoco, resetCoco, sayToCoco, type CocoLine, type CocoState } from './api'
import { navigate } from './router'

export function FirstRun({ state, onConfirm }: { state: CocoState; onConfirm?: () => void }) {
  return (
    <main className="coco">
      <h1>Coco</h1>
      <p className="request">I'm your shopping agent. Before I search, confirm your three conditions.</p>
      <dl className="terms">
        {state.conditions.map((condition) => (
          <div key={condition.id}>
            <dt>{condition.label}</dt>
            <dd>{condition.definition}</dd>
          </div>
        ))}
      </dl>
      <p className="request">They are saved, and every store is asked about them before you see a checkout.</p>
      <button className="primary" onClick={onConfirm}>
        Confirm my conditions
      </button>
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
  state: CocoState
  lines: CocoLine[]
  working: boolean
  onSay?: (text: string) => void
  onReset?: () => void
}) {
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
      <p className="conditions">
        Your conditions:{' '}
        {state.conditions.map((condition) => (
          <span key={condition.id} className="chip">
            {condition.label}
          </span>
        ))}
      </p>
      <div className="talk">
        {lines.map((line, index) => (
          <p key={index} className={`line ${line.who}`}>
            <span className="who">{line.who === 'you' ? 'You' : 'Coco'}</span>
            <span>{line.text}</span>
          </p>
        ))}
        {working && <p className="plain working">Coco is working on it.</p>}
      </div>
      <form className="say" onSubmit={submit}>
        <label htmlFor="say">Tell Coco what you need</label>
        <input id="say" name="say" autoComplete="off" placeholder="A queen mattress under $400, shipping to 94541" disabled={working} />
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
  if (!state.conditions_confirmed) return <FirstRun state={state} onConfirm={() => confirmConditions().then(refresh)} />

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
  return <Talk state={state} lines={lines} working={working} onSay={say} onReset={() => resetCoco().then(refresh)} />
}
