import { NavLink } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type NavItem = {
  to: string
  label: string
  end?: boolean
}

type ShellProps = {
  brand: string
  tag?: string
  title: string
  email?: string
  nav: NavItem[]
  dark?: boolean
  onLogout: () => void
  children: React.ReactNode
}

export function Shell({
  brand,
  tag,
  title,
  email,
  nav,
  dark = false,
  onLogout,
  children,
}: ShellProps) {
  return (
    <div className={cn('min-h-screen grid grid-cols-[220px_1fr]', dark && 'dark')}>
      <aside className="flex flex-col gap-0.5 border-r border-sidebar-border bg-sidebar text-sidebar-foreground px-2.5 py-4">
        <div className="px-3 pb-4 pt-2">
          <div className="text-[15px] font-semibold tracking-tight">{brand}</div>
          {tag ? <div className="mt-1 text-xs text-muted-foreground">{tag}</div> : null}
        </div>
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'rounded-md px-3 py-2.5 text-sm text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
        <div className="mt-auto border-t border-sidebar-border px-3 pb-1.5 pt-3.5 text-xs text-muted-foreground">
          {email || '—'}
        </div>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-col bg-background text-foreground">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b border-border bg-background/85 px-5 backdrop-blur">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <div className="flex items-center gap-2">
            {email ? <span className="text-xs text-muted-foreground">{email}</span> : null}
            <Button variant="outline" size="sm" onClick={onLogout}>
              退出
            </Button>
          </div>
        </header>
        <main className="flex-1 p-5 pb-9">{children}</main>
      </div>
    </div>
  )
}