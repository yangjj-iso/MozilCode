import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { UserApp } from '@/pages/user/UserApp'
import { OpsApp } from '@/pages/ops/OpsApp'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/ops/*" element={<OpsApp />} />
        <Route path="/*" element={<UserApp />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </BrowserRouter>
  )
}