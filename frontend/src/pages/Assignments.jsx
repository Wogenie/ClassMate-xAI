import React, { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, BookOpenCheck, CalendarClock, ChevronDown, ChevronUp,
  FileUp, ListChecks, Loader2, MessageCircleQuestion, Sparkles, X,
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


function SectionList({ title, items, icon }) {
  if (!items || !items.length) return null
  return (
    <div className="text-xs">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-1">
        {icon} {title}
      </div>
      <ul className="space-y-1 text-slate-300">
        {items.map((it, i) => (
          <li key={i} className="flex gap-1.5">
            <span className="text-slate-500">•</span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function StudentAnswers({ a }) {
  const go = (a.clarification && a.clarification.group_open) || {}
  const seen = new Set()
  const entries = []
  for (const x of [...(go.answers || []), ...(go.pending_answers || [])]) {
    const t = (x.text || '').trim()
    if (!t || seen.has(t)) continue
    seen.add(t)
    entries.push(x)
  }
  if (!entries.length) return null
  return (
    <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/25 px-3 py-2.5 space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-300">
        <MessageCircleQuestion size={13} /> Student answers
        {go.status === 'waiting' && (
          <span className="badge bg-amber-500/15 text-amber-300">waiting for more replies</span>
        )}
      </div>
      {entries.map((x, i) => (
        <div key={i} className="text-xs text-slate-200">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-slate-300">{x.sender || 'student'}</span>
            {x.at && <span className="text-slate-500">{new Date(x.at).toLocaleString()}</span>}
            {x.verified === false && (
              <span className="badge bg-amber-500/15 text-amber-300">reply noted — summary will refresh</span>
            )}
          </div>
          <p className="text-slate-200 whitespace-pre-wrap mt-0.5">{x.text}</p>
        </div>
      ))}
    </div>
  )
}

function AssignmentCard({ a, onStatus, onAsk, onUpload }) {
  const [showSolution, setShowSolution] = useState(false)
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

      {a.analysis_source?.understanding_status && (
        <p className="text-[10px] text-slate-600">
          last analyzed {new Date(a.analysis_source.at).toLocaleString()}
        </p>
      )}

      {a.solve_blocked_reason && (
        <div className="rounded-xl bg-amber-500/10 border border-amber-500/25 px-3 py-2.5 text-xs text-amber-200">
          <AlertTriangle size={13} className="inline mr-1.5 -mt-0.5" />
          {a.solve_blocked_reason}
        </div>
      )}

      <StudentAnswers a={a} />

      {a.summary ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300 mb-1">
            <Sparkles size={13} /> AI Summary
          </div>
          <p className="text-sm text-slate-200">{a.summary}</p>
        </div>
      ) : (
        <div className="rounded-xl bg-slate-500/10 border border-dashed border-slate-500/30 px-3 py-2.5 text-xs text-slate-400">
          <div className="flex items-center gap-1.5 mb-0.5">
            <Sparkles size={13} /> AI Summary
          </div>
          <p>The agent's short project description will appear here automatically.</p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2.5">
          <SectionList title="What you need to do" items={u.tasks} icon={<ListChecks size={11} />} />
          <SectionList title="Requirements" items={u.requirements} icon={<AlertTriangle size={11} />} />
          <SectionList title="Submission" items={u.submission_requirements} icon={<FileUp size={11} />} />
        </div>
        <div className="space-y-2.5">
          <SectionList title="Required topics" items={u.required_topics} icon={<BookOpenCheck size={11} />} />
          <SectionList title="Expected outputs" items={u.expected_outputs} icon={<Sparkles size={11} />} />
          {u.objective && u.objective !== 'Not specified' && (
            <div className="text-xs">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Objective</div>
              <p className="text-slate-300">{u.objective}</p>
            </div>
          )}
        </div>
      </div>

      {a.solution && (
        <div className="rounded-xl border border-edge/70 overflow-hidden">
          <button
            onClick={() => setShowSolution((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2.5 text-sm bg-panel hover:bg-edge/40 transition"
          >
            <span className="flex items-center gap-1.5 font-medium">
              <Sparkles size={14} className="text-indigo-300" /> AI Solution
            </span>
            {showSolution ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          {showSolution && (
            <div className="px-4 py-3 border-t border-edge/70 max-h-96 overflow-y-auto">
              <Markdown text={a.solution} />
            </div>
          )}
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-2 pt-1 border-t border-edge/60">
        <div className="flex items-center gap-2 text-xs">
          {a.deadline ? (
            <span className="text-sm font-mono text-amber-200">
              <CalendarClock size={14} className="inline mr-1" /> {a.deadline}
            </span>
          ) : (
            <span className="text-sm text-slate-500">deadline unknown</span>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 flex-wrap">
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

function BucketList({ title, items, onStatus, onAsk, onUpload, tone }) {
  if (!items.length) return null
  return (
    <div className="space-y-2">
      <h3 className={`text-sm font-semibold flex items-center gap-2 ${tone}`}>
        {title} <span className="badge bg-edge text-slate-300">{items.length}</span>
      </h3>
      {items.map((a) => (
        <AssignmentCard key={a.id} a={a} onStatus={onStatus} onAsk={onAsk} onUpload={onUpload} />
      ))}
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
      setData({ assignments, deadlines })
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

  const byStatus = (s) => data.assignments.filter((a) => a.status === s)
  const cardProps = { onStatus: setStatus, onAsk: askDetails, onUpload: upload }

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
        <h2 className="font-semibold flex items-center gap-2">
          <AlertTriangle size={17} className="text-rose-300" /> Deadline radar
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          <BucketList title="⏰ Overdue" items={data.deadlines.overdue} tone="text-rose-300" {...cardProps} />
          <BucketList title="📌 Due today" items={data.deadlines.due_today} tone="text-amber-200" {...cardProps} />
          <BucketList title="⚡ Due within 24h" items={data.deadlines.due_soon} tone="text-amber-300" {...cardProps} />
          <BucketList title="📆 Upcoming" items={data.deadlines.upcoming} tone="text-slate-300" {...cardProps} />
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="font-semibold">All assignments</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {STATUSES.map((s) => (
            <div className="contents" key={s}>
              {byStatus(s).map((a) => (
                <AssignmentCard key={a.id} a={a} {...cardProps} />
              ))}
            </div>
          ))}
          {data.assignments.length === 0 && (
            <p className="text-sm text-slate-500">
              No assignments yet. They appear automatically when your Telegram bot hears about them.
            </p>
          )}
        </div>
      </section>

      {askFor && (
        <AskModal assignment={askFor} onClose={() => setAskFor(null)} onDone={() => { setAskFor(null); load() }} />
      )}
    </div>
  )
}