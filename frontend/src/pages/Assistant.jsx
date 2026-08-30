import React, { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Eraser, Loader2, Mic, Send, Sparkles } from 'lucide-react'
import api, { errText } from '../services/api.js'
import Markdown from '../components/Markdown.jsx'

const SUGGESTIONS = [
  'What assignments do I have this week?',
  'What are the coming deadlines?',
  'Is there any quiz coming?',
  'What did I miss in class?',
  'What should I focus on now?',
]

const MODEL_KEY = 'cmx_llm_model'

export default function Assistant() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const scrollRef = useRef(null)
  const bottomRef = useRef(null)
  const menuRef = useRef(null)

  // scroll the chat container to the LATEST message immediately — both on the
  // very first load (so you land at the end of a long conversation on
  // navigation, no manual scrolling) and after every new message.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: !loaded ? 'auto' : 'smooth',
      block: 'end',
    })
  }, [messages, busy, loaded])

  useEffect(() => {
    api.get('/assistant/models')
      .then(({ data }) => {
        setModels(data.models || [])
        const saved = localStorage.getItem(MODEL_KEY) || ''
        const def = data.default || (data.models || [])[0]?.id || ''
        setModel((data.models || []).some((m) => m.id === saved) ? saved : def)
      })
      .catch(() => {})
  }, [])

  // close the model menu when clicking anywhere else
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen])

  useEffect(() => {
    api
      .get('/assistant/history')
      .then(({ data }) => setMessages(data.map((m) => ({ role: m.role, content: m.content }))))
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [])

  const send = async (text) => {
    const clean = (text || input).trim()
    if (!clean || busy) return
    setMessages((m) => [...m, { role: 'user', content: clean }])
    setInput('')
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/assistant/chat', {
        message: clean,
        model: model || undefined,
      })
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: data.reply || '…' },
      ])
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const pick = (id) => {
    setModel(id)
    localStorage.setItem(MODEL_KEY, id)
    setMenuOpen(false)
  }

  const activeModel = models.find((m) => m.id === model)

  return (
    <div className="max-w-5xl mx-auto flex flex-col h-[calc(100vh-76px)] sm:h-[calc(100vh-92px)]">
      <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <Sparkles size={17} className="text-indigo-400" /> Chat
          </h1>
          <p className="text-xs text-slate-400 hidden sm:inline">Grounded in your Telegram data.</p>
        </div>
        <div className="flex gap-2 items-center" ref={menuRef}>
          {models.length > 0 && (
            <div className="relative">
              <button
                className="btn-ghost text-xs shrink-0"
                onClick={() => setMenuOpen((v) => !v)}
                title="Choose the AI model for this chat"
              >
                <Sparkles size={13} className="inline mr-1.5 text-indigo-400" />
                {activeModel ? activeModel.name : model ? model.split('/').pop() : 'Model'}
                <ChevronDown size={13} className="inline ml-1" />
              </button>
              {menuOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-64 z-20 rounded-xl border border-edge bg-panel shadow-xl overflow-hidden">
                  {models.map((m) => (
                    <button
                      key={m.id}
                      className="w-full text-left px-4 py-2.5 text-xs hover:bg-indigo-500/10 flex items-start justify-between gap-2"
                      onClick={() => pick(m.id)}
                    >
                      <span>
                        <span className="block text-slate-200 font-medium">{m.name}</span>
                        <span className="block text-slate-500 mt-0.5 font-mono text-[10px] truncate">{m.id}</span>
                      </span>
                      {m.id === model && <Check size={14} className="text-indigo-400 mt-1 shrink-0" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            className="btn-ghost text-xs"
            onClick={async () => {
              setMessages([])
              try {
                await api.delete('/assistant/history')
              } catch {
                /* ignore */
              }
            }}
            title="Clear the conversation history"
          >
            <Eraser size={14} className="inline mr-1" /> Clear
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-500/10 text-rose-300 px-4 py-2 rounded-xl text-sm mb-3">{error}</div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 && (
          <div className="card text-center py-10 space-y-4">
            <p className="text-slate-300 text-sm">Ask anything you'd normally ask a classmate:</p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="badge bg-edge hover:bg-indigo-500/20 px-3 py-2 text-sm text-slate-200" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
            </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              className={
                m.role === 'user'
                  ? 'max-w-[92%] bg-indigo-500/90 text-white rounded-2xl rounded-br-md px-4 py-3'
                  : 'max-w-[98%] bg-panel border border-edge rounded-2xl rounded-bl-md px-4 py-3'
              }
            >
              {m.role === 'assistant' ? (
                <Markdown text={m.content} />
              ) : (
                <span className="whitespace-pre-wrap">{m.content}</span>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="bg-panel border border-edge rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2 text-slate-400 text-sm">
              <Loader2 size={16} className="animate-spin" /> thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        className="mt-4 flex gap-2"
      >
        <input
          className="input"
          placeholder="Ask about assignments, deadlines, quizzes, what you missed…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="btn-primary" disabled={busy} type="submit">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </form>
    </div>
  )
}