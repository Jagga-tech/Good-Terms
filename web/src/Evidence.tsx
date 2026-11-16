import type { Row, Sentence } from './api'

export function Status({ status, text }: { status: string; text: string }) {
  return <span className={`status ${status}`}>{text}</span>
}

export function linkText(url: string) {
  const { host, pathname } = new URL(url)
  return host.replace(/^www\./, '') + pathname
}

export function StoreWords({ sentence, date }: { sentence: Sentence; date: string | null }) {
  return (
    <figure className="words">
      {sentence.heading && <figcaption>Under the heading “{sentence.heading}”</figcaption>}
      <blockquote cite={sentence.url}>“{sentence.sentence}”</blockquote>
      <p className="small">
        <a href={sentence.url} target="_blank" rel="noreferrer">
          {linkText(sentence.url)}
        </a>
        {date && <span> · read {date}</span>}
      </p>
    </figure>
  )
}

export function Reply({ row, label }: { row: Row; label: string }) {
  if (!row.assistant_reply && !row.assistant_text) return null
  return (
    <div className="reply">
      <p className="small">
        {label}
        {row.reply_time && <span> · asked {row.reply_time}</span>}
      </p>
      <p>{row.assistant_reply ?? row.assistant_text}</p>
    </div>
  )
}
