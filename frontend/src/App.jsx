import React from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Overview from './pages/Overview.jsx'
import Assistant from './pages/Assistant.jsx'
import Assignments from './pages/Assignments.jsx'
import Schedule from './pages/Schedule.jsx'
import Setup from './pages/Setup.jsx'
import Settings from './pages/Settings.jsx'

function Protected({ children }) {
  const token = localStorage.getItem('cm_token')
  const loc = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: loc }} replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/" element={<Overview />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/assignments" element={<Assignments />} />
        <Route path="/schedule" element={<Schedule />} />
        <Route path="/setup" element={<Setup />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}