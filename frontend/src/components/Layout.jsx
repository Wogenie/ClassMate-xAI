import React, { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Bell,
  BookOpenCheck,
  CalendarClock,
  GraduationCap,
  Inbox as InboxIcon,
  LayoutDashboard,
  Menu,
  MessagesSquare,
  Moon,
  Settings2,
  Sparkles,
  Sun,
  Wrench,
  X,
} from 'lucide-react'
import api from '../services/api.js'
import { applyTheme, getInitialTheme } from '../services/theme.js'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/inbox', label: 'Message Inbox', icon: InboxIcon },
  { to: '/assistant', label: 'Assistant', icon: MessagesSquare },
  { to: '/assignments', label: 'Assignments & Deadlines', icon: BookOpenCheck },
  { to: '/schedule', label: 'Schedule · Quizzes · Missed', icon: CalendarClock },
]

export default function Layout() {
  const nav = useNavigate()
  const [unread, setUnread] = useState(0)
  const [username, setUsername] = useState(localStorage.getItem('cm_user') || '')
  const [displayName, setDisplayName] = useState(localStorage.getItem('cm_name') || '')
  const [picture, setPicture] = useState(localStorage.getItem('cm_picture') || '')
  const [theme, setTheme] = useState(() => getInitialTheme())
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    setDisplayName(localStorage.getItem('cm_name') || localStorage.getItem('cm_user') || '')
    setPicture(localStorage.getItem('cm_picture') || '')
  }, [])

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  const closeDrawer = () => setDrawerOpen(false)

  const loadNotifications = async () => {
    try {
      const { data } = await api.get('/notifications')
      setUnread(data.filter((n) => !n.read).length)
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadNotifications()
    const t = setInterval(loadNotifications, 30000)
    return () => clearInterval(t)
  }, [])

  const logout = () => {
    closeDrawer()
    localStorage.removeItem('cm_token')
    localStorage.removeItem('cm_user')
    localStorage.removeItem('cm_name')
    localStorage.removeItem('cm_email')
    localStorage.removeItem('cm_picture')
    nav('/login')
  }

  const sidebarContent = (
    <>
      <div className="flex items-center gap-2 px-5 py-5 border-b border-edge">
        <span className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center shrink-0">
          <GraduationCap size={20} />
        </span>
        <div className="min-w-0">
          <div className="font-bold text-slate-100 leading-none">Classmate xAI</div>
          <div className="text-[11px] text-slate-400 mt-1 truncate">your digital classmate</div>
        </div>
        <button onClick={closeDrawer} title="Close menu" className="ml-auto p-1.5 rounded-lg hover:bg-edge/50 sm:hidden">
          <X size={18} />
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={closeDrawer}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition ${
                isActive
                  ? 'bg-indigo-500/15 text-indigo-300 font-medium'
                  : 'text-slate-400 hover:bg-edge/50 hover:text-slate-200'
              }`
            }
          >
            <item.icon size={17} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 pb-5 space-y-1 border-t border-edge pt-3">
        <NavLink
          to="/setup"
          onClick={closeDrawer}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition ${
              isActive ? 'bg-edge/70 text-slate-100' : 'text-slate-400 hover:bg-edge/50 hover:text-slate-200'
            }`
          }
        >
          <Wrench size={17} /> Setup & Connection
        </NavLink>
        <NavLink
          to="/settings"
          onClick={closeDrawer}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition ${
              isActive ? 'bg-edge/70 text-slate-100' : 'text-slate-400 hover:bg-edge/50 hover:text-slate-200'
            }`
          }
        >
          <Settings2 size={17} /> Memory & Adaptation
        </NavLink>
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-slate-500 hover:bg-edge/50 hover:text-slate-300 transition"
          title="Log out"
        >
          {picture ? (
            <img src={picture} alt="" className="w-5 h-5 rounded-full object-cover shrink-0" />
          ) : (
            <Sparkles size={17} />
          )}
          <span className="truncate">Log out ({displayName || username})</span>
        </button>
      </div>
    </>
  )

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar (hidden on small screens) */}
      <aside className="hidden sm:flex w-64 shrink-0 border-r border-edge bg-panel/50 flex-col h-full overflow-y-auto">
        {sidebarContent}
      </aside>

      {/* Mobile drawer + overlay */}
      <div
        onClick={closeDrawer}
        className={`fixed inset-0 z-40 bg-black/60 transition-opacity sm:hidden ${
          drawerOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      />
      <aside
        className={`fixed z-50 inset-y-0 left-0 w-72 max-w-[85vw] bg-panel border-r border-edge flex flex-col overflow-y-auto transform transition-transform duration-200 sm:hidden ${
          drawerOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col h-full">
        {/* Mobile top bar */}
        <header className="h-14 shrink-0 border-b border-edge flex items-center gap-2 px-4 sm:justify-end sticky top-0 bg-ink/90 backdrop-blur z-10 sm:px-6">
          <button
            onClick={() => setDrawerOpen(true)}
            title="Open menu"
            className="p-2 rounded-lg hover:bg-edge/50 transition sm:hidden"
          >
            <Menu size={20} />
          </button>
          <span className="font-bold sm:hidden mr-auto truncate">Classmate xAI</span>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="p-2 rounded-lg hover:bg-edge/50 transition"
          >
            <span
              className={`inline-grid transition-transform duration-500 ${theme === 'light' ? 'rotate-180' : ''}`}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </span>
          </button>
          <button onClick={loadNotifications} className="relative p-2 rounded-lg hover:bg-edge/50 transition">
            <Bell size={18} />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] grid place-items-center">
                {unread}
              </span>
            )}
          </button>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="p-3 sm:p-4 md:p-6 max-w-6xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}