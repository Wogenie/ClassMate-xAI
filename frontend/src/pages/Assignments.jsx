import React, { useEffect, useRef, useState } from 'react'
import {
  BookOpenCheck, CalendarClock,
  FileUp, Loader2, MessageCircleQuestion, Sparkles, X,
} from 'lucide-react'
import api, { errText } from '../services/api.js'
import Markdown from '../components/Markdown.jsx'

const STATUSES = ['not_started', 'in_progress', 'submitted', 'completed']
const STATUS_COLOR = {
  not_started: 'bg-slate-500/15 text-slate-300',
  in_progress: 'bg-amber-500/15 text-amber-300',
  submitted: 'bg-sky-500/15 text-sky-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
}

function AssignmentCard({ a, onStatus, onAsk, onUpload }) {
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const u = a.understanding || {}
  const topicTitle = (a.title || a.course).replace(/\s+(?:assignment|assessment|homework|quiz|exam|test)s?\s*$/i, '')

  const onFile = async (e) => {
    const f = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!f || uploading) return
    setUploading(true)
    try {
      await onUpload(a.id, f)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="card space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold">{topicTitle}</div>
          <div className="text-xs text-slate-400 mt-0.5">{a.course}</div>
        </div>
      </div>
      {a.description && <p className="text-sm text-slate-300">{a.description}</p>}

      {/* key detail fields beside the Ask button (outside the AI answer box) */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="badge bg-edge text-slate-300">{a.course}</span>
        {a.deadline ? (
          <span className="text-sm font-mono text-amber-200">
            <CalendarClock size={13} className="inline mr-1" /> {a.deadline}
          </span>
        ) : (
          <span className="badge bg-slate-500/15 text-slate-400">deadline unknown</span>
        )}
        {u.group_or_individual && (
          <span className="badge bg-slate-500/15 text-slate-300">{u.group_or_individual}</span>
        )}
        {u.submission_format && (
          <span className="badge bg-slate-500/15 text-slate-300">Submit: {u.submission_format}</span>
        )}
      </div>

      {a.analysis_source?.understanding_status && (
        <p className="text-[10px] text-slate-600">
          last analyzed {new Date(a.analysis_source.at).toLocaleString()}
        </p>
      )}

      {/* AI answer box — the actual answer to the assignment */}
      {a.solution ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300 mb-1">
            <Sparkles size={13} /> AI Answer
          </div>
          <div className="text-sm text-slate-200 markdown-body"><Markdown text={a.solution} /></div>
        </div>
      ) : a.summary ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300 mb-1">
            <Sparkles size={13} /> AI Answer
          </div>
          <p className="text-sm text-slate-200">{a.summary}</p>
        </div>
      ) : (
        <div className="rounded-xl bg-slate-500/10 border border-dashed border-slate-500/30 px-3 py-2.5 text-xs text-slate-400">
          <div className="flex items-center gap-1.5 mb-0.5">
            <Sparkles size={13} /> AI Answer
          </div>
          <p>Submit an answer or reply in the group and it will appear here automatically.</p>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 flex-wrap pt-1 border-t border-edge/60">
        <button
          className="btn-ghost text-xs"
          onClick={() => onAsk(a)}
          title={`Ask about ${a.title || a.course}`}
        >
          <MessageCircleQuestion size={13} className="inline mr-1" /> Ask details
        </button>
        <button className="btn-ghost text-xs" onClick={() => fileRef.current?.click()} disabled={uploading}>
          {uploading ? <Loader2 size={13} className="animate-spin" /> : <FileUp size={13} className="inline mr-1" />}
          {uploading ? 'Uploading…' : 'Add details'}
        </button>
        <input ref={fileRef} type="file" hidden onChange={onFile}
          accept=".pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp" />
        <select
          className="input !w-auto text-xs py-1.5"
          value={a.status}
          onChange={(e) => onStatus(a.id, e.target.value)}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace('_', ' ')}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

function AskModal({ assignment, onClose, onDone }) {
  const [questions, setQuestions] = useState([])
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .post(`/assignments/${assignment.id}/ask`)
      .then(({ data }) => setQuestions(data.questions || []))
      .catch((e) => setError(errText(e)))
      .finally(() => setLoading(false))
  }, [assignment.id])

  const send = async () => {
    const clean = answer.trim()
    if (!clean || sending) return
    setSending(true)
    setError('')
    try {
      await api.post(`/assignments/${assignment.id}/answer`, { answer: clean })
      onDone()
    } catch (e) {
      setError(errText(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-lg max-h-[85vh] overflow-y-auto space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold flex items-center gap-2">
              <MessageCircleQuestion size={16} className="text-indigo-400" />
              Tell me about «{assignment.title || assignment.course}»
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              I'll only ask what I actually need to understand the project — never the same thing twice.
            </p>
          </div>
          <button className="btn-ghost !p-1.5" onClick={onClose}><X size={16} /></button>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 size={15} className="animate-spin" /> figuring out what to ask…
          </div>
        )}
        {!loading && !error && (
          <>
            {questions.length === 0 ? (
              <p className="text-sm text-slate-300">
                I think I already have enough to understand this project. If it still feels wrong,
                upload the assignment document or add a note below.
              </p>
            ) : (
              <ol className="space-y-2">
                {questions.map((q, i) => (
                  <li key={i} className="text-sm text-slate-200 flex gap-2">
                    <span className="text-indigo-400 shrink-0">{i + 1}.</span>
                    <span>{q}</span>
                  </li>
                ))}
              </ol>
            )}
            <div>
              <textarea
                className="input w-full min-h-[110px]"
                placeholder="Your answer…  (mention what the project is about, tasks, software, submission, etc.)"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
            </div>
          </>
        )}
        {error && <p className="text-sm text-rose-300">{error}</p>}
        {!loading && !error && (
          <div className="flex justify-end gap-2">
            <button className="btn-ghost text-xs" onClick={onClose}>Later</button>
            <button className="btn-primary text-xs" onClick={send} disabled={sending || !answer.trim()}>
              {sending ? <Loader2 size={13} className="animate-spin" /> : null} Send answers
            </button>
          </div>
        )}
      </div>
    </div>
  )
}


export default function Assignments() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [askStatus, setAskStatus] = useState('')
  const [askFor, setAskFor] = useState(null)
  const pollRounds = useRef(0)

  const load = async () => {
    setAskStatus('')
    try {
      const [{ data: assignments }, { data: deadlines }] = await Promise.all([
        api.get('/assignments'),
        api.get('/assignments/deadlines'),
      ])
      const sorted = [...assignments].sort((a, b) => {
        if (!a.deadline && !b.deadline) return 0
        if (!a.deadline) return 1
        if (!b.deadline) return -1
        return new Date(a.deadline) - new Date(b.deadline)
      })
      setData({ assignments: sorted, deadlines })
    } catch (e) {
      setError(errText(e))
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (!data) return
    const pending = data.assignments.filter(
      (a) => !a.summary || a.analysis_source?.status === 'instant'
    )
    if (!pending.length) return
    if (pollRounds.current >= 12) return
    const t = setTimeout(() => {
      pollRounds.current += 1
      load()
    }, 6000)
    return () => clearTimeout(t)
  }, [data])

  const setStatus = async (id, status) => {
    await api.patch(`/assignments/${id}/status`, { status })
    load()
  }

  const askDetails = async (a) => {
    setAskStatus('')
    try {
      const { data } = await api.post(`/assignments/${a.id}/ask`)
      if (data.sent) {
        setAskStatus('The questions were sent to the students in the Telegram group. The agent will add their answers to the assignment automatically.')
      } else {
        setAskFor(a)
      }
    } catch (e) {
      setError(errText(e))
      setAskFor(a)
    }
    load()
  }

  const upload = async (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      await api.post(`/assignments/${id}/upload`, fd)
    } catch (e) {
      setError(errText(e))
    }
    load()
  }

  if (!data)
    return (
      <div className="grid place-items-center py-40 text-slate-400">
        <Loader2 className="animate-spin" />
      </div>
    )

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <BookOpenCheck size={20} className="text-indigo-400" /> Assignments &amp; Deadlines
        </h1>
        <p className="text-sm text-slate-400 mt-1">The Assignment Guardian understands the project — then, only when it's clear, it summarizes it.</p>
      </div>

      {error && <div className="bg-rose-500/10 text-rose-300 px-4 py-3 rounded-xl text-sm">{error}</div>}

      {askStatus && (
        <div className="flex items-start gap-2 bg-sky-500/10 text-sky-200 border border-sky-500/25 px-4 py-3 rounded-xl text-sm">
          <MessageCircleQuestion size={16} className="shrink-0 mt-0.5" />
          <span>{askStatus}</span>
        </div>
      )}

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h2 className="font-semibold flex items-center gap-2">
            <BookOpenCheck size={18} className="text-indigo-400" /> All assignments
            <span className="badge bg-edge text-slate-300">{data.assignments.length}</span>
          </h2>
          <div className="flex items-center gap-2 flex-wrap">
            {data.deadlines.overdue.length > 0 && (
              <span className="badge bg-rose-500/15 text-rose-300">⏰ {data.deadlines.overdue.length} overdue</span>
            )}
            {data.deadlines.due_today.length > 0 && (
              <span className="badge bg-amber-500/15 text-amber-200">📌 {data.deadlines.due_today.length} due today</span>
            )}
            {data.deadlines.due_soon.length > 0 && (
              <span className="badge bg-amber-400/15 text-amber-300">⚡ {data.deadlines.due_soon.length} due soon</span>
            )}
            {data.deadlines.upcoming.length > 0 && (
              <span className="badge bg-slate-500/15 text-slate-300">📆 {data.deadlines.upcoming.length} upcoming</span>
            )}
          </div>
        </div>

        {data.assignments.length === 0 ? (
          <p className="text-sm text-slate-500">
            No assignments yet. They appear automatically when your Telegram bot hears about them.
          </p>
        ) : (
          <div className="space-y-3">
            {data.assignments.map((a) => (
              <AssignmentCard key={a.id} a={a} onStatus={setStatus} onAsk={askDetails} onUpload={upload} />
            ))}
          </div>
        )}
      </section>

      {askFor && (
        <AskModal assignment={askFor} onClose={() => setAskFor(null)} onDone={() => { setAskFor(null); load() }} />
      )}
    </div>
  )
}