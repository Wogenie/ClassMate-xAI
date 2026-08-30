import React, { useEffect, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  KeyRound,
  Loader2,
  MessageCircle,
  Play,
  Plug,
  Save,
  Square,
  XCircle,
} from 'lucide-react'
import api, { errText } from '../services/api.js'

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between w-full px-3 py-2.5 rounded-xl bg-ink border border-edge hover:border-indigo-500/50 transition"
    >
      <span className="text-sm text-slate-300">{label}</span>
      <span className={`w-10 h-6 rounded-full transition relative ${checked ? 'bg-indigo-500' : 'bg-edge'}`}>
        <span
          className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${checked ? 'left-[18px]' : 'left-0.5'}`}
        />
      </span>
    </button>
  )
}

export default function Setup() {
  const [form, setForm] = useState({
    telegram_bot_token: '',
    telegram_api_id: '',
    telegram_api_hash: '',
    groq_api_key: '',
    target_chat: '',
    notifications_enabled: true,
    ocr_screenshots: true,
    poll_after_class: true,
    bot_enabled: false,
  })
  const [saved, setSaved] = useState(false)
  const [botRunning, setBotRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null) // {kind:'ok'|'err', text}
  const [test, setTest] = useState({ groq: null, tg: null })
  const [testing, setTesting] = useState('')

  const load = async () => {
    try {
      const { data } = await api.get('/settings')
      setForm({
        telegram_bot_token: data.telegram_bot_token || '',
        telegram_api_id: data.telegram_api_id || '',
        telegram_api_hash: data.telegram_api_hash || '',
        groq_api_key: data.groq_api_key || '',
        target_chat: data.target_chat || '',
        notifications_enabled: data.notifications_enabled,
        ocr_screenshots: data.ocr_screenshots,
        poll_after_class: data.poll_after_class,
        bot_enabled: data.bot_enabled,
      })
      setBotRunning(data.bot_running)
    } catch (e) {
      setMsg({ kind: 'err', text: errText(e) })
    }
  }

  useEffect(() => {
    load()
  }, [])

  const set = (k) => (e) =>
    setForm((f) => ({ ...f, [k]: e.target ? e.target.value : e }))

  const save = async (e) => {
    if (e) e.preventDefault()
    setBusy(true)
    setSaved(false)
    setMsg(null)
    try {
      const { data } = await api.put('/settings', form)
      setBotRunning(data.bot_running)
      setSaved(true)
      setMsg({ kind: 'ok', text: 'Saved. Keys are encrypted at rest.' })
    } catch (e2) {
      setMsg({ kind: 'err', text: errText(e2) })
    } finally {
      setBusy(false)
    }
  }

  const testConn = async (mode) => {
    setTesting(mode)
    setMsg(null)
    try {
      const { data } = await api.post('/settings/test', {
        ...form,
        mode,
      })
      setTest((t) => ({
        ...t,
        groq: data.groq_ok ? { ok: true, text: data.groq_message } : { ok: false, text: data.groq_message },
        tg: data.telegram_ok ? { ok: true, text: data.telegram_message } : { ok: false, text: data.telegram_message },
      }))
    } catch (e) {
      setMsg({ kind: 'err', text: errText(e) })
    } finally {
      setTesting('')
    }
  }

  const toggleBot = async (wantOn) => {
    setBusy(true)
    setMsg(null)
    try {
      if (wantOn) {
        const { data } = await api.post('/settings/start')
        setBotRunning(true)
        setForm((f) => ({ ...f, bot_enabled: true }))
        setMsg({ kind: 'ok', text: data.status })
      } else {
        await api.post('/settings/stop')
        setBotRunning(false)
        setForm((f) => ({ ...f, bot_enabled: false }))
        setMsg({ kind: 'ok', text: 'Bot stopped.' })
      }
    } catch (e) {
      setMsg({ kind: 'err', text: errText(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-1">Setup &amp; Connection</h1>
      <p className="text-sm text-slate-400 mb-6">
        Bring your <strong className="text-slate-200">own</strong> keys — every user of the platform provides their own
        Telegram bot token and Groq API key. They are encrypted and never shown again.
      </p>

      {msg && (
        <div
          className={`mb-4 px-4 py-3 rounded-xl text-sm ${
            msg.kind === 'ok' ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'
          }`}
        >
          {msg.text}
        </div>
      )}

      <form onSubmit={save} className="space-y-6">
        <section className="card space-y-4">
          <h2 className="font-semibold flex items-center gap-2">
            <Bot size={18} className="text-indigo-400" /> Telegram bot
          </h2>
          <div>
            <label className="label">Bot token (from @BotFather)</label>
            <input
              className="input font-mono text-xs"
              placeholder="123456:ABC..."
              value={form.telegram_bot_token}
              onChange={set('telegram_bot_token')}
              autoComplete="off"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">API ID (optional)</label>
              <input className="input" placeholder="e.g. 123456" value={form.telegram_api_id} onChange={set('telegram_api_id')} />
            </div>
            <div>
              <label className="label">API hash (optional)</label>
              <input className="input font-mono text-xs" placeholder="hex hash" value={form.telegram_api_hash} onChange={set('telegram_api_hash')} />
            </div>
          </div>
          <div>
            <label className="label">Target chat — group @username or numeric ID</label>
            <input
              className="input"
              placeholder="@your_course_group or -1001234567890"
              value={form.target_chat}
              onChange={set('target_chat')}
            />
          </div>
        </section>

        <section className="card space-y-4">
          <h2 className="font-semibold flex items-center gap-2">
            <KeyRound size={18} className="text-indigo-400" /> Groq API key
          </h2>
          <div>
            <label className="label">Groq API key (powers the assistant & ingestion)</label>
            <input
              className="input font-mono text-xs"
              placeholder="gsk_..."
              value={form.groq_api_key}
              onChange={set('groq_api_key')}
              autoComplete="off"
            />
          </div>
        </section>

        <section className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <MessageCircle size={18} className="text-indigo-400" /> Behavior
          </h2>
          <Toggle checked={form.notifications_enabled} onChange={set('notifications_enabled')} label="Telegram notifications (deadlines, polls, summaries)" />
          <Toggle checked={form.ocr_screenshots} onChange={set('ocr_screenshots')} label="Read text from announcement screenshots (OCR)" />
          <Toggle checked={form.poll_after_class} onChange={set('poll_after_class')} label="Auto lecture-sync poll after each class" />
        </section>

        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={busy}>
            <Save size={16} className="inline mr-1" /> {saved ? 'Saved ✓' : 'Save settings'}
          </button>
          <button type="button" className="btn-ghost" onClick={() => testConn('groq')} disabled={!!testing}>
            {testing === 'groq' ? <Loader2 size={16} className="inline mr-1 animate-spin" /> : <Plug size={16} className="inline mr-1" />}
            Test Groq
          </button>
          <button type="button" className="btn-ghost" onClick={() => testConn('telegram')} disabled={!!testing}>
            {testing === 'telegram' ? <Loader2 size={16} className="inline mr-1 animate-spin" /> : <Plug size={16} className="inline mr-1" />}
            Test Telegram
          </button>
          <button type="button" className="btn-ghost" onClick={() => testConn('all')} disabled={!!testing}>
            <Plug size={16} className="inline mr-1" /> Test both
          </button>
        </div>

        {(test.groq || test.tg) && (
          <div className="card space-y-2 text-sm">
            {test.groq && (
              <div className="flex items-start gap-2">
                {test.groq.ok ? (
                  <CheckCircle2 size={17} className="text-emerald-400 mt-0.5" />
                ) : (
                  <XCircle size={17} className="text-rose-400 mt-0.5" />
                )}
                <span className={test.groq.ok ? 'text-emerald-300' : 'text-rose-300'}>
                  Groq: {test.groq.text}
                </span>
              </div>
            )}
            {test.tg && (
              <div className="flex items-start gap-2">
                {test.tg.ok ? (
                  <CheckCircle2 size={17} className="text-emerald-400 mt-0.5" />
                ) : (
                  <XCircle size={17} className="text-rose-400 mt-0.5" />
                )}
                <span className={test.tg.ok ? 'text-emerald-300' : 'text-rose-300'}>
                  Telegram: {test.tg.text}
                </span>
              </div>
            )}
          </div>
        )}

        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <Bot size={18} className={botRunning ? 'text-emerald-400' : 'text-slate-500'} />
            Live bot{' '}
            {botRunning ? (
              <span className="badge bg-emerald-500/15 text-emerald-300">ONLINE</span>
            ) : (
              <span className="badge bg-edge text-slate-400">STOPPED</span>
            )}
          </h2>
          <p className="text-xs text-slate-500">
            While running, the bot listens to {form.target_chat || 'the target chat'} and your assistant can also ask it
            to post to the group. Save before starting.
          </p>
          <div className="flex gap-3">
            <button type="button" className="btn-primary" onClick={() => toggleBot(true)} disabled={busy || botRunning}>
              <Play size={16} className="inline mr-1" /> Start bot
            </button>
            <button type="button" className="btn-ghost" onClick={() => toggleBot(false)} disabled={busy || !botRunning}>
              <Square size={16} className="inline mr-1" /> Stop bot
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}