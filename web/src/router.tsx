import { useEffect, useState, type ReactNode } from 'react'

const here = () => window.location.pathname + window.location.search

export function useRoute() {
  const [route, setRoute] = useState(here)
  useEffect(() => {
    const update = () => setRoute(here())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  return new URL(route, window.location.origin)
}

export function navigate(to: string, replace = false) {
  window.history[replace ? 'replaceState' : 'pushState'](null, '', to)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function Link({ to, children, current }: { to: string; children: ReactNode; current?: boolean }) {
  return (
    <a
      href={to}
      aria-current={current ? 'page' : undefined}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return
        event.preventDefault()
        navigate(to)
      }}
    >
      {children}
    </a>
  )
}

export function withParam(name: string, value: string | null) {
  const here = typeof window === 'undefined' ? new URL('http://app/') : new URL(window.location.href)
  if (value === null) here.searchParams.delete(name)
  else here.searchParams.set(name, value)
  const query = here.searchParams.toString()
  return here.pathname + (query ? `?${query}` : '')
}
