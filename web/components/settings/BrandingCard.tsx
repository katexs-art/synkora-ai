'use client'

import { useState, useEffect } from 'react'
import { apiClient } from '@/lib/api/client'
import { extractErrorMessage } from '@/lib/api/error'

interface Branding {
  platform_name: string
  platform_logo_url: string
  support_email: string
  primary_color: string
  secondary_color: string
}

const EMPTY: Branding = { platform_name: '', platform_logo_url: '', support_email: '', primary_color: '#10b981', secondary_color: '#0ea5e9' }

export default function BrandingCard() {
  const [b, setB] = useState<Branding>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    apiClient
      .request('GET', '/api/v1/platform-settings/branding')
      .then((d: any) => {
        setB({
          platform_name: d?.platform_name || '',
          platform_logo_url: d?.platform_logo_url || '',
          support_email: d?.support_email || '',
          primary_color: d?.primary_color || '#10b981',
          secondary_color: d?.secondary_color || '#0ea5e9',
        })
      })
      .catch((e: any) => console.error('branding load failed', e))
      .finally(() => setLoading(false))
  }, [])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await apiClient.request('PUT', '/api/v1/platform-settings/branding', b)
      setMsg({ type: 'success', text: 'Branding saved — refresh to see it applied.' })
    } catch (err: any) {
      setMsg({ type: 'error', text: extractErrorMessage(err, 'Failed to save branding') })
    } finally {
      setSaving(false)
    }
  }

  const field = 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent bg-white text-gray-900'
  const label = 'block text-sm font-medium text-gray-700 mb-2'

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold text-gray-900 mb-1">Branding</h2>
      <p className="text-sm text-gray-600 mb-5">Platform name, logo, support email and brand colors — applied across the whole platform.</p>
      {msg && (
        <div className={`mb-4 p-3 rounded-lg text-sm ${msg.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>{msg.text}</div>
      )}
      <form onSubmit={save} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={label}>Platform name</label>
            <input className={field} value={b.platform_name} onChange={(e) => setB({ ...b, platform_name: e.target.value })} placeholder="Katexs" />
          </div>
          <div>
            <label className={label}>Support email</label>
            <input className={field} type="email" value={b.support_email} onChange={(e) => setB({ ...b, support_email: e.target.value })} placeholder="support@katexs.com" />
          </div>
        </div>
        <div>
          <label className={label}>Logo URL</label>
          <input className={field} value={b.platform_logo_url} onChange={(e) => setB({ ...b, platform_logo_url: e.target.value })} placeholder="https://app.katexs.tech/logo.png" />
          {b.platform_logo_url && (
            <div className="mt-2 flex items-center gap-3 p-2 bg-gray-50 rounded-lg w-fit">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={b.platform_logo_url} alt="logo preview" className="h-8 w-auto bg-white rounded px-1" onError={(e: any) => { e.target.style.display = 'none' }} onLoad={(e: any) => { e.target.style.display = '' }} />
              <span className="text-xs text-gray-500">Preview</span>
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={label}>Primary color (buttons, links, highlights)</label>
            <div className="flex items-center gap-2">
              <input type="color" value={b.primary_color} onChange={(e) => setB({ ...b, primary_color: e.target.value })} className="h-10 w-14 border border-gray-300 rounded-lg cursor-pointer bg-white" />
              <input className={field} value={b.primary_color} onChange={(e) => setB({ ...b, primary_color: e.target.value })} />
            </div>
          </div>
          <div>
            <label className={label}>Secondary color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={b.secondary_color} onChange={(e) => setB({ ...b, secondary_color: e.target.value })} className="h-10 w-14 border border-gray-300 rounded-lg cursor-pointer bg-white" />
              <input className={field} value={b.secondary_color} onChange={(e) => setB({ ...b, secondary_color: e.target.value })} />
            </div>
          </div>
        </div>
        <div className="flex justify-end">
          <button type="submit" disabled={saving || loading} className="px-6 py-3 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {saving ? 'Saving...' : 'Save Branding'}
          </button>
        </div>
      </form>
    </div>
  )
}
