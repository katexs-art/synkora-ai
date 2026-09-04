import * as React from "react"
export const Label = ({ children, className, htmlFor }: any) => (
  <label htmlFor={htmlFor} className={`text-sm font-medium ${className || ''}`}>{children}</label>
)
