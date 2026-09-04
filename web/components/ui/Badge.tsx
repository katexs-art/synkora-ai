import * as React from "react"
export const Badge = ({ children, className, variant }: any) => (
  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-800 ${className || ''}`}>{children}</span>
)
