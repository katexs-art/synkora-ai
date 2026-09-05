'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Phone, Sparkles, Building2, ArrowRight } from 'lucide-react'
import toast from 'react-hot-toast'
import { apiClient } from '@/lib/api/client'

const INDUSTRIES = [
  'Dental',
  'HVAC',
  'Legal',
  'Real Estate',
  'Medical',
  'Automotive',
  'Salon & Spa',
  'Home Services',
  'E-commerce',
  'Restaurant',
  'Insurance',
  'General',
]

export default function NewAgentPage() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [industry, setIndustry] = useState('HVAC')
  const [description, setDescription] = useState('')
  const [building, setBuilding] = useState(false)
  const [lane, setLane] = useState<'voice' | 'chat'>('voice')

  async function handleBuild() {
    if (!name.trim()) {
      toast.error('Give your agent a name')
      return
    }
    setBuilding(true)
    try {
      const res = await apiClient.request('POST', '/api/v1/katexs/auto-build', {
        business_name: name.trim(),
        industry,
        description: description.trim() || null,
        lane,
      })
      if (!res?.success) {
        toast.error(res?.detail || res?.message || 'Build failed')
        return
      }
      const slug = res.agent?.slug || res.slug
      if (!slug) {
        toast.error('Agent built but no slug returned')
        return
      }
      toast.success(`“${res.agent?.agent_name || name.trim()}” is live!`)
      if (lane === 'voice') {
        router.push(`/agents/${slug}/voice-studio`)
      } else {
        router.push(`/agents/${slug}`)
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message
      toast.error(typeof detail === 'string' ? detail : 'Build failed — check the name is unique')
    } finally {
      setBuilding(false)
    }
  }

  const fieldCls =
    'w-full px-3 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 bg-white'

  return (
    <div className="min-h-screen bg-[#faf7f2]">
      <div className="max-w-2xl mx-auto px-6 py-12">
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-100 text-emerald-700 text-xs font-bold uppercase tracking-wide mb-4">
            <Sparkles className="w-3.5 h-3.5" /> AI workforce builder
          </div>
          <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">Build your AI agent</h1>
          <p className="mt-2 text-gray-600 text-sm">
            Describe what it should do — Katexs assembles the agent, voice line and live configuration in under a minute.
          </p>
        </div>

        <div className="bg-white rounded-2xl border border-[#e5d9ca] shadow-[0_24px_60px_-46px_rgba(73,45,23,0.3)] p-6 md:p-8 space-y-6">
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
                <Building2 className="w-4 h-4 text-gray-400" /> Business / agent name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Miami Cool Air"
                className={fieldCls}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Industry</label>
              <select value={industry} onChange={(e) => setIndustry(e.target.value)} className={fieldCls}>
                {INDUSTRIES.map((i) => (
                  <option key={i} value={i}>{i}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">What should it handle?</label>
            <textarea
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="AC repair and maintenance appointments, after-hours emergency calls, answering FAQs about pricing and service areas…"
              className={`${fieldCls} resize-none`}
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setLane('voice')}
              className={`flex-1 rounded-xl border p-4 text-left transition-colors ${lane === 'voice' ? 'border-emerald-500 bg-emerald-50 ring-1 ring-emerald-500' : 'border-gray-200 hover:border-gray-300'}`}
            >
              <Phone className={`w-5 h-5 mb-2 ${lane === 'voice' ? 'text-emerald-600' : 'text-gray-400'}`} />
              <p className="text-sm font-bold text-gray-900">Phone agent</p>
              <p className="text-xs text-gray-500 mt-0.5">Answers calls, books appointments — live on a number</p>
            </button>
            <button
              onClick={() => setLane('chat')}
              className={`flex-1 rounded-xl border p-4 text-left transition-colors ${lane === 'chat' ? 'border-emerald-500 bg-emerald-50 ring-1 ring-emerald-500' : 'border-gray-200 hover:border-gray-300'}`}
            >
              <Sparkles className={`w-5 h-5 mb-2 ${lane === 'chat' ? 'text-emerald-600' : 'text-gray-400'}`} />
              <p className="text-sm font-bold text-gray-900">Chat agent</p>
              <p className="text-xs text-gray-500 mt-0.5">Website widget conversations — embed anywhere</p>
            </button>
          </div>

          <button
            onClick={handleBuild}
            disabled={building}
            className="w-full inline-flex items-center justify-center gap-2 px-6 py-3 text-sm font-bold text-white bg-emerald-600 rounded-xl disabled:opacity-60 hover:bg-emerald-700 transition-colors"
          >
            {building ? (
              <>
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Building agent… (voice line provisioning)
              </>
            ) : (
              <>
                Build agent <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
