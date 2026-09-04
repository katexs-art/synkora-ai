import * as React from "react"
export const Textarea = ({ className, ...props }: any) => (
  <textarea className={`border rounded px-2 py-1 text-sm w-full ${className || ''}`} {...props} />
)
