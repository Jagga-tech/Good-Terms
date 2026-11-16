import { useEffect, useState } from 'react'
import { getCoco } from './api'
import BuyersCheck from './BuyersCheck'
import Coco from './Coco'
import { MerchantBox } from './MerchantView'
import { Link, navigate, useRoute } from './router'

export function Footer() {
  return <footer>Prototype. Not affiliated with Shopify.</footer>
}

export function parseRoute(url: URL) {
  const check = url.pathname.match(/^\/check\/(\d+)$/)
  const asked = (name: string) => url.searchParams.get(name)
  if (!check && url.pathname !== '/') return { screen: 'none' as const }
  return {
    screen: 'shop' as const,
    id: check ? check[1] : null,
    store: asked('store'),
    review: asked('review'),
    merchantStore: asked('m'),
  }
}

export function NothingYet({ backup }: { backup: boolean }) {
  return (
    <section className="box">
      <h1>Buyer's Check</h1>
      <p className="plain">Nothing is being checked yet.</p>
      <p className="request">Tell Coco what you need. Each store's answers appear here as its pages are read.</p>
      {backup && (
        <p className="saved">
          <Link to="/check/2">Open the saved check from 2026-11-15</Link>
        </p>
      )}
    </section>
  )
}

export default function App() {
  const url = useRoute()
  const route = parseRoute(url)
  const [backup, setBackup] = useState(false)
  useEffect(() => {
    getCoco().then((state) => setBackup(state.backup_mode))
  }, [])
  useEffect(() => {
    if (route.screen === 'none') navigate('/', true)
  }, [route.screen])

  if (route.screen === 'none') return null
  return (
    <>
      <header>
        <span className="brand">GoodTerms</span>
      </header>
      <div className="split">
        <Coco checkShown={route.id} />
        <div className="pane">
          {route.id ? (
            <BuyersCheck id={route.id} openStore={route.store} review={route.review} merchant={route.merchantStore} />
          ) : (
            <>
              <NothingYet backup={backup} />
              <MerchantBox check={null} domain={null} />
            </>
          )}
        </div>
      </div>
      <Footer />
    </>
  )
}
