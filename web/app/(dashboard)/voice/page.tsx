'use client'

import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api/client'
import Link from 'next/link'

interface VoiceAgent {
  id: string
  agent_name: string
  slug: string
  status: string
  greeting: string
  enabled: boolean
  vapi_assistant_id: string
  phone_provisioned: boolean
  updated_at?: string
}
interface VNumber { id: string; phone_number: string; agent_id?: string | null; is_active: boolean }
interface VCall { id: string; caller_number: string; agent_name: string; status: string; duration_seconds?: number | null; started_at?: string | null }

function fmtDur(s?: number | null) {
  if (!s) return '—'
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

export default function VoicePage() {
  const [data, setData] = useState<{ agents: VoiceAgent[]; numbers: VNumber[]; calls: VCall[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    apiClient
      .request('GET', '/api/v1/katexs/voice-overview')
      .then((d: any) => setData(d || { agents: [], numbers: [], calls: [] }))
      .catch((e: any) => setError(e?.message || 'Failed to load voice overview'))
  }, [])

  if (error) return <div className="max-w-6xl mx-auto p-6 text-red-600">{error}</div>
  if (!data) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500"></div>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">Voice Agents</h1>
          <p className="mt-2 text-gray-600">Phone agents powered by Katexs — calls, numbers and provisioning.</p>
        </div>
        <Link href="/agents/new" className="px-5 py-2.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 text-sm font-semibold">
          + New voice agent
        </Link>
      </div>

      {/* stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white shadow rounded-lg p-5">
          <div className="text-3xl font-extrabold text-gray-900">{data.agents.length}</div>
          <div className="text-sm text-gray-500 mt-1">Voice agents</div>
        </div>
        <div className="bg-white shadow rounded-lg p-5">
          <div className="text-3xl font-extrabold text-gray-900">{data.numbers.length}</div>
          <div className="text-sm text-gray-500 mt-1">Phone numbers</div>
        </div>
        <div className="bg-white shadow rounded-lg p-5">
          <div className="text-3xl font-extrabold text-gray-900">{data.calls.length}</div>
          <div className="text-sm text-gray-500 mt-1">Recent calls</div>
        </div>
      </div>

      {/* voice agents */}
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Your voice agents</h2>
      {data.agents.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-10 text-center">
          <p className="text-gray-500 mb-4">No voice agents yet. Describe one and it builds itself — phone-ready.</p>
          <Link href="/agents/new" className="px-5 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-semibold">
            Create your first voice agent
          </Link>
        </div>
      ) : (
        <div className="space-y-3 mb-8">
          {data.agents.map((a) => (
            <div key={a.id} className="bg-white shadow rounded-lg p-5 flex flex-col md:flex-row md:items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-gray-900 truncate">{a.agent_name}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold uppercase ${a.enabled ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                    {a.enabled ? 'Live' : 'Setup pending'}
                  </span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold uppercase ${a.phone_provisioned ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'}`}>
                    {a.phone_provisioned ? 'Katexs connected' : 'No number yet'}
                  </span>
                </div>
                {a.greeting && <p className="text-sm text-gray-500 mt-1 truncate">“{a.greeting}”</p>}
                {a.vapi_assistant_id && <p className="text-xs text-gray-400 mt-0.5 font-mono">assistant: {a.vapi_assistant_id.slice(0, 8)}…</p>}
              </div>
              <div className="flex gap-2">
                <Link href={`/agents/${a.slug}/voice-studio`} className="text-sm text-emerald-600 hover:text-emerald-700 font-medium">Voice Studio</Link>
                <Link href={`/agents/${a.slug}`} className="text-sm text-gray-600 hover:text-gray-800 font-medium">Open</Link>
                <Link href={`/agents/${a.slug}/settings/phone`} className="text-sm text-gray-600 hover:text-gray-800 font-medium">Numbers</Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* numbers */}
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Phone numbers</h2>
      {data.numbers.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-6 text-gray-500 text-sm mb-8">No numbers attached yet — numbers get linked to a voice agent when provisioned.</div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden mb-8">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
              <tr><th className="text-left p-3">Number</th><th className="text-left p-3">Status</th></tr>
            </thead>
            <tbody>
              {data.numbers.map((n) => (
                <tr key={n.id} className="border-t border-gray-100">
                  <td className="p-3 font-mono">{n.phone_number}</td>
                  <td className="p-3">{n.is_active ? 'Active' : 'Inactive'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* calls */}
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Recent calls</h2>
      {data.calls.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-6 text-gray-500 text-sm">No calls yet — once a number is live, transcripts and call records appear here.</div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
              <tr>
                <th className="text-left p-3">Caller</th>
                <th className="text-left p-3">Agent</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Duration</th>
                <th className="text-left p-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {data.calls.map((c) => (
                <tr key={c.id} className="border-t border-gray-100">
                  <td className="p-3 font-mono">{c.caller_number}</td>
                  <td className="p-3">{c.agent_name || '—'}</td>
                  <td className="p-3 capitalize">{c.status}</td>
                  <td className="p-3">{fmtDur(c.duration_seconds)}</td>
                  <td className="p-3 text-gray-500">{c.started_at ? new Date(c.started_at).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
