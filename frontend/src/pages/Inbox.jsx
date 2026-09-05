import React, { useEffect, useState } from 'react'
import {
  BookOpenCheck,
  FileQuestion,
  Inbox as InboxIcon,
  Loader2,
  MessageSquare,
  Paperclip,
} from 'lucide-react'
import api, { errText } from '../services/api.js'

const TABS = [
  { key: 'all', label: 'All messages', icon: MessageSquare, accent: 'text-indigo-300' },
  { key: 'assignment', label: 'Assignments', icon: BookOpenCheck, accent: 'text-amber-300' },
  { key: 'exam', label: 'Exams & Quizzes', icon: FileQuestion, accent: 'text-emerald-300' },
  { key: 'other', label: 'Other', icon: MessageSquare, accent: 'text-slate-300' },
]

function MessageRow({ m }) {
  const ts = m.timestamp ? new Date(m.timestamp) : null
  return (
    <div className="flex items-start gap-3 px-1 py-3">
      <div className="w-9 h-9 rounded-full bg-indigo-500/20 grid place-items-center text-xs font-semibold text-indigo-300 shrink-0">
        {(m.sender_name || m.sender || '?').charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <span className="text-sm font-medium text-slate-200">{m.sender}</span>
          {ts && !isNaN(ts) && (
            <span className="text-[11px] text-slate-500">
              {ts.toLocaleDateString()} {ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
        <p className="text-sm text-slate-300 whitespace-pre-wrap mt-1">{m.text}</p>
        {m.media_type && m.media_type !== 'none' && (
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-500 mt-1">
            <Paperclip size={11} /> media attached
          </span>
        )}
      </div>
    </div>
  )
}

export default function Inbox() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('all')

  const load = async () => {
    try {
      const { data } = await api.get('/dashboard/inbox')
      setData(data)
    } catch (e) {
      setError(errText(e))
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  if (!data)
    return (
      <div className="grid place-items-center py-40 text-slate-400">
        <Loader2 className="animate-spin" />
      </div>
    )

  const allItems = [...(data.assignment || []), ...(data.exam || []), ...(data.other || [])]
    .sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0))

  const items = tab === 'all' ? allItems : (data[tab] || []).slice().reverse()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <InboxIcon size={20} className="text-indigo-400" /> All TG Messages
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Every message your bot has sensed from Telegram, stored so you can always refer back. Nothing is missed.
        </p>
      </div>

      {error && <div className="bg-rose-500/10 text-rose-300 px-4 py-3 rounded-xl text-sm">{error}</div>}

      <div className="flex items-center gap-2 flex-wrap">
        {TABS.map((t) => {
          const Icon = t.icon
          const count =
            t.key === 'all'
              ? allItems.length
              : (data[t.key] || []).length
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`badge cursor-pointer transition ${
                tab === t.key ? 'bg-indigo-500/25 text-indigo-200' : 'bg-edge text-slate-400 hover:text-slate-200'
              }`}
            >
              <Icon size={13} className={`inline mr-1 ${t.accent}`} /> {t.label}
              <span className="ml-1 opacity-70">{count}</span>
            </button>
          )
        })}
      </div>

      <div className="card">
        {items.length === 0 ? (
          <p className="text-sm text-slate-500 px-1 py-6">
            No messages here yet. They appear automatically when your Telegram bot hears from the group.
          </p>
        ) : (
          <div className="divide-y divide-edge/50">
            {items.map((m) => (
              <MessageRow key={m.id} m={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
