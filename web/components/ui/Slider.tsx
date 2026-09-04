import * as React from "react"
export const Slider = ({ value, onValueChange, min, max, step, className }: any) => (
  <input type="range" min={min || 0} max={max || 100} step={step || 1} value={value?.[0] ?? value ?? 0} onChange={(e) => onValueChange?.([parseFloat(e.target.value)])} className={`w-full ${className || ''}`} />
)
