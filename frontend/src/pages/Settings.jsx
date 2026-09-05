import React, { useEffect, useState } from 'react'
import {
  Bell,
  Brain,
  Check,
  FileUp,
  Loader2,
  MessageSquarePlus,
  Trash2,
} from 'lucide-react'
import api, { errText } from '../services/api.js'

export default function Settings() {
  const [rules, setRules] = useState([])
  const [ruleInput, setRuleInput] = useState('')
  const [notifs, setNotifs] = useState([])
  const [uploaded, setUploaded] = useState(null)
  const [file, setFile] = useState(null)
  const [course, setCourse] = useState('')
  const [courses, setCourses] = useState([])
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const loadCourses = async () => {
    try {
      const { data } = await api.get('/ingest/courses')
      setCourses(data)
    } catch {
      /* ignore */
    }
  }

  const load = async () => {
    try {
      const [r, n] = await Promise.all([
        api.get('/preferences'),
        api.get('/notifications'),
      ])
      setRules(r.data)
      setNotifs(n.data)
      await loadCourses()
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    load()
  }, [])

  const teach = async (e) => {
    e.preventDefault()
    if (!ruleInput.trim()) return
    setBusy(true)
    try {
      await api.post('/preferences', { statement: ruleInput })
      setRuleInput('')
      await load()
      setMsg({ kind: 'ok', text: 'Learned. This rule is scoped to YOUR account only.' })
    } catch (e2) {
      setMsg({ kind: 'err', text: errText(e2) })
    } finally {
      setBusy(false)
    }
  }

  const markRead = async (id) => {
    await api.post(`/notifications/${id}/read`)
    await load()
  }

  const upload = async (e) => {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setUploaded(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('course', course)
      const { data } = await api.post('/ingest/document', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploaded(data)
      setFile(null)
      setCourse('')
      await loadCourses()
    } catch (e2) {
      setMsg({ kind: 'err', text: errText(e2) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold">Memory &amp; Adaptation</h1>
        <p className="text-sm text-slate-400 mt-1">
          The classmate teaches itself about <em>you</em> — scoped rules, never the global prompt.
        </p>
      </div>

      {msg && (
        <div className={`px-4 py-3 rounded-xl text-sm ${msg.kind === 'ok' ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'}`}>
          {msg.text}
        </div>
      )}

      <section className="card space-y-3">
        <h2 className="font-semibold flex items-center gap-2">
          <Brain size={18} className="text-indigo-400" /> Teach the agent
        </h2>
        <form onSubmit={teach} className="flex gap-2">
          <input
            className="input"
            placeholder={'e.g. "Alice is actually the lecturer" · "When I say ML I mean Machine Learning" · "Always show me deadlines first" · "Don\'t trust announcements from Bob"'}
            value={ruleInput}
            onChange={(e) => setRuleInput(e.target.value)}
          />
          <button className="btn-primary shrink-0" disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <MessageSquarePlus size={16} />}
          </button>
        </form>
        {rules.length > 0 ? (
          <ul className="space-y-1.5">
            {rules.map((r) => (
              <li key={r.id} className="flex items-center justify-between text-sm bg-ink rounded-xl px-3 py-2 border border-edge/60">
                <span>
                  <span className="badge bg-edge text-slate-300 mr-2">{r.kind}</span>
                  {r.value}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-500">
            Nothing learned yet. Tell the agent things like who the lecturer is, what a nickname means, or what to
            prioritize — it will remember and adapt.
          </p>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="font-semibold flex items-center gap-2">
          <FileUp size={18} className="text-emerald-400" /> Add course outline
        </h2>
        <p className="text-xs text-slate-500">
          Upload your course outline(s) (PDF, DOCX, PPTX, TXT). They are embedded and stored in
          ChromaDB, then compared against what was said in class to reconstruct missed classes.
        </p>
        <form onSubmit={upload} className="flex flex-wrap gap-2 items-end">
          <div className="flex-1 min-w-[180px]">
            <label className="label">Course name</label>
            <input
              className="input"
              placeholder="e.g. Data Structures & Algorithms"
              value={course}
              onChange={(e) => setCourse(e.target.value)}
              list="ingested-courses"
            />
            <datalist id="ingested-courses">
              {courses.map((c) => (
                <option key={c.id} value={c.course} />
              ))}
            </datalist>
          </div>
          <div className="flex-1 min-w-[180px]">
            <label className="label">Outline file (PDF, DOCX, PPTX, TXT)</label>
            <input
              type="file"
              accept=".pdf,.docx,.doc,.pptx,.ppt,.txt,.md"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm text-slate-400 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-edge file:text-slate-200"
            />
          </div>
          <button className="btn-primary" disabled={busy || !file}>
            <Check size={16} className="inline mr-1" /> Ingest
          </button>
        </form>
        {courses.length > 0 && (
          <div className="pt-1">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
              Outline already injected — don't re-upload these
            </div>
            <ul className="space-y-1">
              {courses.map((c) => (
                <li key={c.id} className="flex items-center justify-between text-xs bg-ink rounded-lg px-3 py-1.5 border border-edge/60">
                  <span className="font-medium text-slate-200">{c.course}</span>
                  <span className="text-slate-500 truncate ml-2">{c.files.length} file(s)</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {uploaded && (
          <p className="text-xs text-emerald-300">
            ✓ Embedded {uploaded.chunks} outline chunks into course “{uploaded.course}” (local embeddings in
            ChromaDB). The missed-class summarizer will search them to reconstruct today's class.
          </p>
        )}
      </section>

      <section className="card space-y-2">
        <h2 className="font-semibold flex items-center gap-2">
          <Bell size={18} className="text-amber-300" /> Notifications ({notifs.filter((n) => !n.read).length} unread)
        </h2>
        {notifs.length === 0 && <p className="text-sm text-slate-500">No notifications yet.</p>}
        {notifs.map((n) => (
          <div key={n.id} className={`rounded-xl px-3 py-2.5 border text-sm ${n.read ? 'border-edge/50 bg-ink/40 text-slate-500' : 'border-edge bg-ink text-slate-200'}`}>
            <div className="flex items-center justify-between">
              <span className="font-medium">{n.title}</span>
              {!n.read && (
                <button onClick={() => markRead(n.id)} className="text-xs text-slate-400 hover:text-indigo-300">
                  mark read
                </button>
              )}
            </div>
            <p className="text-xs mt-0.5">{n.body}</p>
            <p className="text-[10px] text-slate-600 mt-1">{n.created_at}</p>
          </div>
        ))}
      </section>
    </div>
  )
}