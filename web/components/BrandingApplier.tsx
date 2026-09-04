'use client'

import { useEffect } from 'react'

// Fetches public platform branding and applies it as CSS variables + a global event
// so logo consumers (sidebar, auth pages) can update without a refactor.
export default function BrandingApplier() {
  useEffect(() => {
    let cancelled = false
    fetch('https://api.katexs.tech/api/v1/platform-settings/branding/public', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: any) => {
        if (cancelled || !d) return
        const root = document.documentElement
        if (d.primary_color) root.style.setProperty('--k-primary', d.primary_color)
        if (d.secondary_color) root.style.setProperty('--k-secondary', d.secondary_color)
        if (d.platform_logo_url) root.style.setProperty('--k-logo', `url("${d.platform_logo_url}")`)
        window.dispatchEvent(new CustomEvent('katexs:branding', { detail: d }))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])
  return null
}
