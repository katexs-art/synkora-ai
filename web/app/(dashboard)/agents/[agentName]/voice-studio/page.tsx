'use client'

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { Phone, Save, RefreshCw, Key, ChevronDown, ChevronUp, Cable, Play, Volume2, PhoneCall, ShoppingCart, X, Mic, Square, Send } from 'lucide-react'
import toast from 'react-hot-toast'
import { apiClient } from '@/lib/api/client'
import { saveVapiCredential, checkCredential } from '@/lib/api/phone'
import AgentPageShell, { AgentPagePanel } from '@/components/agents/AgentPageShell'

interface Catalog {
  voices: { voiceId: string; name: string; provider: string; language: string }[]
  voice_providers: { value: string; label: string }[]
  models: Record<string, string[]>
  transcribers: Record<string, string[]>
  languages: { value: string; label: string }[]
}

const emptyCatalog: Catalog = { voices: [], voice_providers: [], models: {}, transcribers: {}, languages: [] }

export default function VoiceStudioPage() {
  const params = useParams()
  const slug = params.agentName as string

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [provisioned, setProvisioned] = useState(false)
  const [assistantId, setAssistantId] = useState('')
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog)
  const [showRaw, setShowRaw] = useState(false)
  const [raw, setRaw] = useState<any>(null)
  const [vapiKey, setVapiKey] = useState('')
  const [vapiCredConfigured, setVapiCredConfigured] = useState(false)

  // brain
  const [systemPrompt, setSystemPrompt] = useState('')
  const [llmProvider, setLlmProvider] = useState('anthropic')
  const [llmModel, setLlmModel] = useState('claude-sonnet-4-5')
  const [temperature, setTemperature] = useState(0.6)
  const [maxTokens, setMaxTokens] = useState(2048)
  const [llmApiKey, setLlmApiKey] = useState('')
  const [usesPlatformKey, setUsesPlatformKey] = useState(true)

  // call flow
  const [firstMessage, setFirstMessage] = useState('')
  const [endCallMessage, setEndCallMessage] = useState('')
  const [language, setLanguage] = useState('en')

  // voice
  const [voiceProvider, setVoiceProvider] = useState('11labs')
  const [voiceId, setVoiceId] = useState('EXAVITQu4vr4xnSDxMaL')
  const [speed, setSpeed] = useState(1.0)
  const [stability, setStability] = useState(0.5)
  const [similarity, setSimilarity] = useState(0.75)

  // transcriber
  const [sttProvider, setSttProvider] = useState('deepgram')
  const [sttModel, setSttModel] = useState('nova-2')

  // behavior
  const [silenceTimeout, setSilenceTimeout] = useState(30)
  const [maxDuration, setMaxDuration] = useState(300)
  const [recording, setRecording] = useState(false)
  const [denoise, setDenoise] = useState(true)
  const [interruptWords, setInterruptWords] = useState(2)
  const [threshold, setThreshold] = useState(0.5)

  // analysis
  const [summaryEnabled, setSummaryEnabled] = useState(false)
  const [structuredEnabled, setStructuredEnabled] = useState(false)

  // samples / test-call / billing
  const [previewing, setPreviewing] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [testTab, setTestTab] = useState<'talk' | 'phone'>('talk')
  const [testNumber, setTestNumber] = useState('')
  const [testCalling, setTestCalling] = useState(false)
  const [billing, setBilling] = useState<any>(null)
  const [buying, setBuying] = useState<number | null>(null)

  // in-browser talk test
  const [talkMsgs, setTalkMsgs] = useState<{ role: 'user' | 'agent'; text: string }[]>([])
  const [talkBusy, setTalkBusy] = useState(false)
  const [talkListening, setTalkListening] = useState(false)
  const [talkInput, setTalkInput] = useState('')
  const [convId, setConvId] = useState<string | null>(null)
  const [recognition, setRecognition] = useState<any>(null)

  useEffect(() => {
    load()
  }, [slug])

  async function load() {
    try {
      setLoading(true)
      const [vc, cred] = await Promise.all([
        apiClient.request('GET', `/api/v1/katexs/voice-assistant/${slug}`).catch(() => null),
        checkCredential('vapi').catch(() => ({ configured: false })),
      ])
      setVapiCredConfigured(!!cred?.configured)
      setBilling(await apiClient.request('GET', `/api/v1/katexs/voice-billing`).catch(() => null))
      if (!vc || !vc.success) {
        setProvisioned(false)
        return
      }
      setProvisioned(vc.agent.provisioned)
      setAssistantId(vc.agent.assistant_id || '')
      setCatalog(vc.catalog || emptyCatalog)
      const b = vc.brain || {}
      setSystemPrompt(b.system_prompt || '')
      setLlmProvider(b.provider || 'anthropic')
      setLlmModel(b.model || 'claude-sonnet-4-5')
      setTemperature(typeof b.temperature === 'number' ? b.temperature : 0.6)
      setMaxTokens(b.max_tokens || 2048)
      setUsesPlatformKey(b.uses_platform_key !== false)
      const c = vc.call || {}
      setFirstMessage(c.first_message || '')
      setEndCallMessage(c.end_call_message || '')
      setLanguage(c.language || 'en')
      const v = vc.vapi || {}
      if (v.voice?.provider) setVoiceProvider(v.voice.provider)
      if (v.voice?.voiceId) setVoiceId(v.voice.voiceId)
      if (typeof v.voice?.speed === 'number') setSpeed(v.voice.speed)
      if (typeof v.voice?.stability === 'number') setStability(v.voice.stability)
      if (typeof v.voice?.similarityBoost === 'number') setSimilarity(v.voice.similarityBoost)
      if (v.transcriber?.provider) setSttProvider(v.transcriber.provider)
      if (v.transcriber?.model) setSttModel(v.transcriber.model)
      if (typeof v.silenceTimeoutSeconds === 'number') setSilenceTimeout(v.silenceTimeoutSeconds)
      if (typeof v.maxDurationSeconds === 'number') setMaxDuration(v.maxDurationSeconds)
      if (typeof v.recordingEnabled === 'boolean') setRecording(v.recordingEnabled)
      if (typeof v.backgroundDenoisingEnabled === 'boolean') setDenoise(v.backgroundDenoisingEnabled)
      if (typeof v.numWordsToInterruptAssistant === 'number') setInterruptWords(v.numWordsToInterruptAssistant)
      if (typeof v.interruptionThreshold === 'number') setThreshold(v.interruptionThreshold)
      const an = v.analysis || {}
      setSummaryEnabled(!!an.summary_enabled)
      setStructuredEnabled(!!an.structured_data_enabled)
      setRaw(v.raw || null)
    } catch {
      toast.error('Failed to load voice studio')
    } finally {
      setLoading(false)
    }
  }

  const voicesForProvider = useMemo(
    () => catalog.voices.filter((v) => v.provider === voiceProvider),
    [catalog.voices, voiceProvider]
  )

  const llmModels = catalog.models[llmProvider] || []
  const sttModels = catalog.transcribers[sttProvider] || ['nova-2']

  async function playSample() {
    if (previewing) return
    setPreviewing(true)
    try {
      const resp = await apiClient.axios.get(`/api/v1/katexs/voice-preview?provider=${encodeURIComponent(voiceProvider)}&voice_id=${encodeURIComponent(voiceId)}`, { responseType: 'blob', validateStatus: (st) => st === 200 })
      const blob = resp.data as Blob
      if (!blob.type.includes('audio')) {
        const txt = await blob.text()
        let detail = 'Sample failed'
        try { detail = JSON.parse(txt).detail || detail } catch { /* keep */ }
        throw new Error(detail)
      }
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => { setPreviewing(false); URL.revokeObjectURL(url) }
      audio.onerror = () => { setPreviewing(false); toast.error('Audio playback failed in this browser') }
      await audio.play()
      setPreviewing(false)
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (e: any) {
      setPreviewing(false)
      const detail = e?.response?.data?.detail || e?.message
      toast.error(typeof detail === 'string' && detail.length > 5 && detail.length < 200 ? detail : 'Sample unavailable')
    }
  }

  async function startTestCall() {
    if (!testNumber.trim()) return
    setTestCalling(true)
    try {
      const res = await apiClient.request('POST', `/api/v1/katexs/voice-assistant/${slug}/test-call`, { customer_number: testNumber.trim() })
      setTestOpen(false)
      setTestNumber('')
      toast.success(`Calling ${res.calling} from ${res.from || 'your agent number'} — pick up!`)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Test call failed — add a phone number to this agent first (Numbers)')
    } finally {
      setTestCalling(false)
    }
  }

  async function buyMinutes(minutes: number) {
    setBuying(minutes)
    try {
      const res = await apiClient.request('POST', `/api/v1/katexs/voice-topup`, { minutes })
      if (res?.checkout_url) {
        window.open(res.checkout_url, '_blank')
      } else {
        toast(res?.message || 'Checkout is being enabled — quote ready', { icon: '🧾' })
      }
    } catch (e: any) {
      toast.error(e?.message || 'Purchase failed')
    } finally {
      setBuying(null)
    }
  }

  async function handleSaveVapiKey() {
    if (!vapiKey.trim()) return
    try {
      await saveVapiCredential(vapiKey.trim())
      setVapiKey('')
      setVapiCredConfigured(true)
      toast.success('Your Vapi API key saved — numbers & billing now run on your Vapi account')
      await load()
    } catch {
      toast.error('Failed to save Vapi API key')
    }
  }

  // ---------------- in-browser talk test ----------------
  const micSupported = typeof window !== 'undefined' && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)

  function speakText(text: string) {
    return new Promise<void>((resolve) => {
      apiClient.axios
        .get(`/api/v1/katexs/voice-preview?provider=${encodeURIComponent(voiceProvider)}&voice_id=${encodeURIComponent(voiceId)}&text=${encodeURIComponent(text.slice(0, 380))}`, {
          responseType: 'blob',
          validateStatus: (st) => st === 200,
        })
        .then((resp) => {
          const url = URL.createObjectURL(resp.data as Blob)
          const audio = new Audio(url)
          audio.onended = () => { URL.revokeObjectURL(url); resolve() }
          audio.onerror = () => resolve()
          audio.play().catch(() => resolve())
        })
        .catch(() => resolve())
    })
  }

  async function talkSend(text: string) {
    const trimmed = text.trim()
    if (!trimmed || talkBusy) return
    setTalkInput('')
    setTalkMsgs((m) => [...m, { role: 'user', text: trimmed }])
    setTalkBusy(true)
    try {
      const res = await apiClient.request('POST', `/api/v1/katexs/voice-assistant/${slug}/talk`, {
        text: trimmed,
        conversation_id: convId || undefined,
      })
      setConvId(res.conversation_id || convId)
      const reply = res.reply || 'Sorry, I did not catch that.'
      setTalkMsgs((m) => [...m, { role: 'agent', text: reply }])
      await speakText(reply)
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message
      setTalkMsgs((m) => [...m, { role: 'agent', text: typeof detail === 'string' ? detail : 'Connection failed' }])
    } finally {
      setTalkBusy(false)
    }
  }

  function toggleMic() {
    if (talkListening) {
      recognition?.stop()
      setTalkListening(false)
      return
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      toast.error('This browser has no speech recognition — type below instead')
      return
    }
    const rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (ev: any) => {
      const t = ev.results?.[0]?.[0]?.transcript
      if (t) talkSend(t)
    }
    rec.onend = () => setTalkListening(false)
    rec.onerror = () => setTalkListening(false)
    setRecognition(rec)
    setTalkListening(true)
    try {
      rec.start()
    } catch {
      setTalkListening(false)
    }
  }

  function closeTalk() {
    recognition?.stop()
    setTalkListening(false)
    setTestOpen(false)
    setTalkMsgs([])
    setConvId(null)
    setTestNumber('')
  }

  async function handleSave() {
    setSaving(true)
    try {
      const payload: any = {
        first_message: firstMessage,
        end_call_message: endCallMessage,
        language,
        system_prompt: systemPrompt,
        voice: { provider: voiceProvider, voice_id: voiceId, speed, stability, similarity_boost: similarity },
        transcriber: { provider: sttProvider, model: sttModel, language },
        model: { provider: llmProvider, model: llmModel, temperature, max_tokens: maxTokens },
        advanced: {
          silence_timeout_seconds: silenceTimeout,
          max_duration_seconds: maxDuration,
          recording_enabled: recording,
          background_denoising_enabled: denoise,
          num_words_to_interrupt_assistant: interruptWords,
          interruption_threshold: threshold,
        },
        analysis: { summary_enabled: summaryEnabled, structured_data_enabled: structuredEnabled },
      }
      if (llmApiKey.trim()) {
        payload.model.api_key = llmApiKey.trim()
      }
      const res = await apiClient.request('PUT', `/api/v1/katexs/voice-assistant/${slug}`, payload)
      if (llmApiKey.trim()) {
        setLlmApiKey('')
        setUsesPlatformKey(false)
        toast.success('Saved — using your own LLM key')
      } else {
        toast.success(res?.message || 'Voice configuration saved & synced to live assistant')
      }
    } catch (e: any) {
      toast.error(e?.message || 'Failed to save voice configuration')
    } finally {
      setSaving(false)
    }
  }

  const fieldCls =
    'w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 bg-white'
  const labelCls = 'text-sm font-medium text-gray-700'
  const hintCls = 'text-xs text-gray-500 mt-0.5'
  const toggleBtn = (on: boolean) =>
    `relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${on ? 'bg-emerald-600' : 'bg-gray-200'}`

  if (loading) {
    return (
      <AgentPageShell agentName={slug} title="Voice Agent Studio" description="Full voice configuration — LLM, voice, transcriber and call behavior." icon={Phone} badge="Voice">
        <AgentPagePanel>
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        </AgentPagePanel>
      </AgentPageShell>
    )
  }

  return (
    <AgentPageShell
      agentName={slug}
      title="Voice Agent Studio"
      description="Everything a phone agent needs — LLM, voice, transcriber, call behavior and analysis. Changes sync to live calls instantly."
      icon={Phone}
      badge="Voice"
      actions={
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTestOpen(true)}
            disabled={!provisioned}
            title={provisioned ? 'Ring your phone with this agent' : 'Provision the assistant first'}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded-lg disabled:opacity-40 hover:bg-emerald-700 transition-colors"
          >
            <PhoneCall className="w-4 h-4" /> Test agent
          </button>
          <button
            onClick={load}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Refresh from live
          </button>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Status strip */}
        <AgentPagePanel>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4 text-sm">
            <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold uppercase ${provisioned ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
              <Cable className="w-3.5 h-3.5" /> {provisioned ? 'Assistant live' : 'Not provisioned'}
            </span>
            {assistantId && <span className="text-xs font-mono text-gray-500">assistant: {assistantId}</span>}
            <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold uppercase ${vapiCredConfigured ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'}`}>
              {vapiCredConfigured ? 'Your Vapi key' : 'Katexs-managed Vapi'}
            </span>
            <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold uppercase ${usesPlatformKey ? 'bg-gray-100 text-gray-500' : 'bg-blue-100 text-blue-700'}`}>
              {usesPlatformKey ? 'Katexs-managed LLM' : 'Your LLM key'}
            </span>
          </div>
        </AgentPagePanel>

        {!provisioned && (
          <AgentPagePanel>
            <div className="p-6 text-sm text-gray-600">
              This agent has no voice assistant provisioned yet. Rebuild it through the voice builder or describe-build flow to provision one — then all options below become editable.
            </div>
          </AgentPagePanel>
        )}

        {/* Connections & keys */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900 flex items-center gap-2"><Key className="w-4 h-4 text-gray-400" /> Connections & API keys</h2>
            <div className="grid md:grid-cols-2 gap-5">
              <div className="space-y-2">
                <label className={labelCls}>Vapi API key (optional — bring your own)</label>
                <p className={hintCls}>Leave blank to use the Katexs-managed provider. Add your own Vapi key to control phone numbers, carriers and billing on your account.</p>
                <div className="flex gap-2">
                  <input type="password" value={vapiKey} onChange={(e) => setVapiKey(e.target.value)} placeholder={vapiCredConfigured ? 'Replace your key…' : 'sk-...'} className={fieldCls} />
                  <button onClick={handleSaveVapiKey} disabled={!vapiKey.trim()} className="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg disabled:opacity-50 hover:bg-gray-700 transition-colors">
                    Save
                  </button>
                </div>
              </div>
              <div className="space-y-2">
                <label className={labelCls}>LLM API key (optional — bring your own)</label>
                <p className={hintCls}>Leave blank to run on Katexs (Claude). Add your own Anthropic or OpenAI key to pay your own LLM costs.</p>
                <div className="flex gap-2">
                  <input type="password" value={llmApiKey} onChange={(e) => setLlmApiKey(e.target.value)} placeholder="sk-ant-... / sk-..." className={fieldCls} />
                  <span className="px-3 py-2 text-xs text-gray-400 whitespace-nowrap">saves with config</span>
                </div>
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* LLM / brain */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900">LLM — agent brain</h2>
            <div className="grid md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className={labelCls}>Provider</label>
                <select value={llmProvider} onChange={(e) => { setLlmProvider(e.target.value); if (catalog.models[e.target.value]?.length) setLlmModel(catalog.models[e.target.value][0]) }} className={fieldCls}>
                  {Object.keys(catalog.models).length === 0 ? (
                    <>
                      <option value="anthropic">Anthropic</option>
                      <option value="openai">OpenAI</option>
                    </>
                  ) : (
                    Object.keys(catalog.models).map((p) => <option key={p} value={p}>{p}</option>)
                  )}
                </select>
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Model</label>
                <select value={llmModel} onChange={(e) => setLlmModel(e.target.value)} className={fieldCls}>
                  {(llmModels.length ? llmModels : ['claude-sonnet-4-5', 'gpt-4o']).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Temperature: {temperature.toFixed(1)}</label>
                <input type="range" min={0} max={1.5} step={0.1} value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} className="w-full mt-3" />
              </div>
            </div>
            <div className="space-y-2">
              <label className={labelCls}>System prompt (persona)</label>
              <textarea rows={7} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} className={`${fieldCls} resize-y font-mono text-xs`} />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className={labelCls}>Max tokens</label>
                <input type="number" min={64} max={8192} step={64} value={maxTokens} onChange={(e) => setMaxTokens(parseInt(e.target.value) || 2048)} className={fieldCls} />
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* Call flow */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900">Call flow</h2>
            <div className="space-y-2">
              <label className={labelCls}>First message (greeting)</label>
              <textarea rows={2} value={firstMessage} onChange={(e) => setFirstMessage(e.target.value)} className={`${fieldCls} resize-none`} />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className={labelCls}>End call message</label>
                <textarea rows={2} value={endCallMessage} onChange={(e) => setEndCallMessage(e.target.value)} className={`${fieldCls} resize-none`} />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Language</label>
                <select value={language} onChange={(e) => setLanguage(e.target.value)} className={fieldCls}>
                  {(catalog.languages.length ? catalog.languages : [{ value: 'en', label: 'English' }, { value: 'es', label: 'Spanish' }]).map((l) => (
                    <option key={l.value} value={l.value}>{l.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* Voice */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900">Voice (text-to-speech)</h2>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className={labelCls}>Voice provider</label>
                <select value={voiceProvider} onChange={(e) => { setVoiceProvider(e.target.value); const first = catalog.voices.find((v) => v.provider === e.target.value); if (first) setVoiceId(first.voiceId) }} className={fieldCls}>
                  {(catalog.voice_providers.length ? catalog.voice_providers : [{ value: '11labs', label: 'ElevenLabs' }, { value: 'openai', label: 'OpenAI' }]).map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Voice</label>
                <div className="flex gap-2">
                  <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)} className={fieldCls}>
                    {voicesForProvider.map((v) => (
                      <option key={v.voiceId} value={v.voiceId}>{v.name}{v.language ? ` (${v.language})` : ''} — {v.voiceId.slice(0, 8)}…</option>
                    ))}
                    {voiceId && !voicesForProvider.some((v) => v.voiceId === voiceId) && <option value={voiceId}>{voiceId} (custom)</option>}
                  </select>
                  <button
                    onClick={playSample}
                    disabled={previewing}
                    title="Play voice sample"
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-semibold text-gray-700 bg-gray-100 border border-gray-200 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors whitespace-nowrap"
                  >
                    {previewing ? <Volume2 className="w-4 h-4 animate-pulse" /> : <Play className="w-4 h-4" />}
                    {previewing ? 'Playing…' : 'Sample'}
                  </button>
                </div>
                <p className={hintCls}>Hear the voice before you commit. Custom voice IDs (e.g. ElevenLabs) also work.</p>
              </div>
            </div>
            <div className="grid md:grid-cols-3 gap-4">
              <div className="space-y-1">
                <label className={labelCls}>Speed: {speed.toFixed(2)}</label>
                <input type="range" min={0.5} max={2} step={0.05} value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))} className="w-full mt-3" />
              </div>
              <div className="space-y-1">
                <label className={labelCls}>Stability: {stability.toFixed(2)}</label>
                <input type="range" min={0} max={1} step={0.05} value={stability} onChange={(e) => setStability(parseFloat(e.target.value))} className="w-full mt-3" />
              </div>
              <div className="space-y-1">
                <label className={labelCls}>Similarity: {similarity.toFixed(2)}</label>
                <input type="range" min={0} max={1} step={0.05} value={similarity} onChange={(e) => setSimilarity(parseFloat(e.target.value))} className="w-full mt-3" />
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* Transcriber */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900">Speech-to-text (transcriber)</h2>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className={labelCls}>Provider</label>
                <select value={sttProvider} onChange={(e) => { setSttProvider(e.target.value); const list = catalog.transcribers[e.target.value]; if (list?.length) setSttModel(list[0]) }} className={fieldCls}>
                  {Object.keys(catalog.transcribers).length === 0 ? (
                    <>
                      <option value="deepgram">Deepgram</option>
                      <option value="openai">OpenAI</option>
                    </>
                  ) : (
                    Object.keys(catalog.transcribers).map((p) => <option key={p} value={p}>{p}</option>)
                  )}
                </select>
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Model</label>
                <select value={sttModel} onChange={(e) => setSttModel(e.target.value)} className={fieldCls}>
                  {sttModels.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* Behavior */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-5 p-6">
            <h2 className="text-base font-bold text-gray-900">Call behavior</h2>
            <div className="grid md:grid-cols-2 gap-x-8 gap-y-5">
              <div className="space-y-2">
                <label className={labelCls}>Silence timeout (seconds)</label>
                <input type="number" min={1} max={120} value={silenceTimeout} onChange={(e) => setSilenceTimeout(parseInt(e.target.value) || 30)} className={fieldCls} />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Max call duration (seconds)</label>
                <input type="number" min={30} max={7200} value={maxDuration} onChange={(e) => setMaxDuration(parseInt(e.target.value) || 300)} className={fieldCls} />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Words to interrupt assistant</label>
                <input type="number" min={1} max={50} value={interruptWords} onChange={(e) => setInterruptWords(parseInt(e.target.value) || 2)} className={fieldCls} />
              </div>
              <div className="space-y-1">
                <label className={labelCls}>Interruption sensitivity: {threshold.toFixed(2)}</label>
                <input type="range" min={0} max={1} step={0.05} value={threshold} onChange={(e) => setThreshold(parseFloat(e.target.value))} className="w-full mt-3" />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className={labelCls}>Record calls</p>
                  <p className={hintCls}>Recording URLs appear in call details</p>
                </div>
                <button onClick={() => setRecording(!recording)} className={toggleBtn(recording)}>
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${recording ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className={labelCls}>Background noise suppression</p>
                  <p className={hintCls}>Cleaner audio in noisy environments</p>
                </div>
                <button onClick={() => setDenoise(!denoise)} className={toggleBtn(denoise)}>
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${denoise ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
            </div>
          </div>
        </AgentPagePanel>

        {/* Analysis */}
        <AgentPagePanel>
          <div className="max-w-3xl space-y-4 p-6">
            <h2 className="text-base font-bold text-gray-900">After-call analysis</h2>
            <div className="flex items-center justify-between">
              <div>
                <p className={labelCls}>Post-call summary</p>
                <p className={hintCls}>Generate a summary when the call ends</p>
              </div>
              <button onClick={() => setSummaryEnabled(!summaryEnabled)} className={toggleBtn(summaryEnabled)}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${summaryEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className={labelCls}>Structured data extraction</p>
                <p className={hintCls}>Pull leads, intent and key details from calls</p>
              </div>
              <button onClick={() => setStructuredEnabled(!structuredEnabled)} className={toggleBtn(structuredEnabled)}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${structuredEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
          </div>
        </AgentPagePanel>

        {/* Minutes & usage */}
        {billing && (
          <AgentPagePanel>
            <div className="max-w-3xl p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-gray-900 flex items-center gap-2"><ShoppingCart className="w-4 h-4 text-gray-400" /> Voice minutes</h2>
                  <p className="text-xs text-gray-500 mt-1">Billed per minute at a flat rate — no surprise fees. Unused minutes never expire.</p>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-extrabold text-gray-900">{billing.minutes?.available?.toLocaleString() ?? '—'}</div>
                  <div className="text-xs text-gray-500">minutes available</div>
                </div>
              </div>
              <div className="grid md:grid-cols-4 gap-3 mt-5">
                {(billing.packs || []).map((p: any) => (
                  <button
                    key={p.minutes}
                    onClick={() => buyMinutes(p.minutes)}
                    disabled={buying !== null}
                    className="rounded-xl border border-gray-200 bg-gray-50 hover:bg-emerald-50 hover:border-emerald-300 transition-colors p-4 text-left disabled:opacity-50"
                  >
                    <div className="text-lg font-extrabold text-gray-900">{p.minutes.toLocaleString()} min</div>
                    <div className="text-sm text-emerald-700 font-semibold mt-0.5">${(p.price_cents / 100).toFixed(2)}</div>
                    <div className="text-[11px] text-gray-400 mt-1">${(p.price_cents / 100 / p.minutes).toFixed(2)}/min</div>
                  </button>
                ))}
              </div>
              {buying !== null && <p className="text-xs text-gray-500 mt-3">{buying.toLocaleString()} min purchase…</p>}
              {!billing.stripe_enabled && (
                <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mt-4">
                  Payments are being enabled — your quote is ready and minutes activate the moment checkout goes live.
                </p>
              )}
            </div>
          </AgentPagePanel>
        )}

        {/* Raw JSON */}
        {raw && (
          <AgentPagePanel>
            <div className="p-6">
              <button onClick={() => setShowRaw(!showRaw)} className="inline-flex items-center gap-2 text-sm font-semibold text-gray-700 hover:text-gray-900">
                {showRaw ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                Full live assistant config (raw)
              </button>
              {showRaw && (
                <pre className="mt-4 p-4 bg-gray-900 text-gray-100 rounded-lg text-[11px] leading-relaxed overflow-x-auto max-h-96 overflow-y-auto">
                  {JSON.stringify(raw, null, 2)}
                </pre>
              )}
            </div>
          </AgentPagePanel>
        )}

        {/* Save */}
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving || !provisioned}
            className="inline-flex items-center gap-2 px-6 py-2.5 text-sm font-bold text-white bg-emerald-600 rounded-lg disabled:opacity-50 hover:bg-emerald-700 transition-colors shadow-lg"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Syncing to live…' : 'Save & sync to live assistant'}
          </button>
        </div>
      </div>

      {/* Test modal — browser talk (default) or phone call */}
      {testOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-gray-100">
              <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2"><PhoneCall className="w-5 h-5 text-emerald-600" /> Test this agent</h3>
              <button onClick={closeTalk} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
            </div>
            <div className="flex gap-1 px-6 pt-4">
              <button
                onClick={() => setTestTab('talk')}
                className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${testTab === 'talk' ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
              >
                Talk in browser
              </button>
              <button
                onClick={() => setTestTab('phone')}
                disabled={!provisioned}
                className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40 ${testTab === 'phone' ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
              >
                Call my phone
              </button>
            </div>

            {testTab === 'talk' ? (
              <div className="flex flex-col flex-1 min-h-0 p-6">
                <p className="text-xs text-gray-500 mb-3">Talk to the live agent right here — no phone needed. Uses the agent&apos;s actual brain and its selected voice.</p>
                <div className="flex-1 overflow-y-auto space-y-2 mb-4 min-h-[140px] max-h-64 bg-gray-50 rounded-xl p-3">
                  {talkMsgs.length === 0 && (
                    <p className="text-xs text-gray-400 text-center py-6">Press the mic and say hi — or type below.</p>
                  )}
                  {talkMsgs.map((m, i) => (
                    <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <span className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap ${m.role === 'user' ? 'bg-emerald-600 text-white rounded-br-sm' : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'}`}>
                        {m.text}
                      </span>
                    </div>
                  ))}
                  {talkBusy && <p className="text-xs text-gray-400 animate-pulse text-center">agent is thinking…</p>}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={toggleMic}
                    disabled={talkBusy || !micSupported}
                    title={micSupported ? (talkListening ? 'Stop listening' : 'Speak') : 'Speech not supported here'}
                    className={`inline-flex items-center justify-center w-11 h-11 rounded-full transition-colors disabled:opacity-40 ${talkListening ? 'bg-red-500 text-white animate-pulse' : 'bg-gray-900 text-white hover:bg-gray-700'}`}
                  >
                    {talkListening ? <Square className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                  </button>
                  <input
                    value={talkInput}
                    onChange={(e) => setTalkInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') talkSend(talkInput) }}
                    placeholder={micSupported ? '…or type a message' : 'Type your message here'}
                    className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
                  />
                  <button
                    onClick={() => talkSend(talkInput)}
                    disabled={!talkInput.trim() || talkBusy}
                    className="inline-flex items-center justify-center w-11 h-11 rounded-full bg-emerald-600 text-white disabled:opacity-40 hover:bg-emerald-700 transition-colors"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
                <p className="text-[11px] text-gray-400 mt-2">
                  {talkListening ? 'Listening… speak now' : `Voice: ${voiceId.slice(0, 10)}… — replies are spoken with this voice`}
                </p>
              </div>
            ) : (
              <div className="p-6">
                <p className="text-sm text-gray-600 mb-4">
                  Enter your phone number — the agent will call you from its number so you can have a real conversation over the line.
                </p>
                <input
                  type="tel"
                  value={testNumber}
                  onChange={(e) => setTestNumber(e.target.value)}
                  placeholder="+14155551234"
                  autoFocus
                  className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500"
                />
                <button
                  onClick={startTestCall}
                  disabled={!testNumber.trim() || testCalling}
                  className="mt-4 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-bold text-white bg-emerald-600 rounded-lg disabled:opacity-50 hover:bg-emerald-700 transition-colors"
                >
                  <PhoneCall className="w-4 h-4" />
                  {testCalling ? 'Calling you…' : 'Call my phone'}
                </button>
                <p className="text-[11px] text-gray-400 mt-3 text-center">Uses the agent&apos;s attached phone number · standard call charges may apply</p>
              </div>
            )}
          </div>
        </div>
      )}
    </AgentPageShell>
  )
}
