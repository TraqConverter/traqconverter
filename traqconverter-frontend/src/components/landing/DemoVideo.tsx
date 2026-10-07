"use client"

import { useEffect, useRef, useState, useSyncExternalStore } from "react"

const REDUCED = "(prefers-reduced-motion: reduce)"

function subscribeReduced(onChange: () => void) {
  const m = window.matchMedia(REDUCED)
  m.addEventListener("change", onChange)
  return () => m.removeEventListener("change", onChange)
}

// The server render assumes reduced motion, so nothing starts before the browser has said otherwise.
export function useReducedMotion() {
  return useSyncExternalStore(subscribeReduced, () => window.matchMedia(REDUCED).matches, () => true)
}

type Props = {
  src: string
  poster: string
  label: string
  width?: number
  height?: number
  // The hero clip: metadata is fetched up front and the browser may start it before the observer runs.
  eager?: boolean
  loop?: boolean
  onEnded?: () => void
  frame?: boolean
}

// A silent product clip: plays only while on screen, never with reduced motion, and always has a pause button.
export default function DemoVideo({
  src,
  poster,
  label,
  width = 1280,
  height = 800,
  eager = false,
  loop = true,
  onEnded,
  frame = true,
}: Props) {
  const ref = useRef<HTMLVideoElement>(null)
  const reduced = useReducedMotion()
  const [userPaused, setUserPaused] = useState(false)
  const [playing, setPlaying] = useState(false)
  // Below-the-fold clips fetch their poster only when they come near the viewport.
  const [near, setNear] = useState(eager)
  const autoplay = !reduced && !userPaused

  useEffect(() => {
    const v = ref.current
    if (!v || near) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setNear(true)
      },
      { rootMargin: "600px 0px" },
    )
    io.observe(v)
    return () => io.disconnect()
  }, [near])

  useEffect(() => {
    const v = ref.current
    if (!v || !autoplay) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void v.play().catch(() => {})
        else v.pause()
      },
      { threshold: 0.35 },
    )
    io.observe(v)
    return () => {
      io.disconnect()
      v.pause()
    }
  }, [autoplay])

  const toggle = () => {
    const v = ref.current
    if (!v) return
    if (v.paused) {
      setUserPaused(false)
      void v.play().catch(() => {})
    } else {
      setUserPaused(true)
      v.pause()
    }
  }

  return (
    <div
      style={{
        position: "relative",
        background: "#ffffff",
        border: frame ? "1px solid #e7ddc5" : undefined,
        borderRadius: frame ? 16 : 0,
        boxShadow: frame ? "0 18px 44px rgba(30,30,20,0.10)" : undefined,
        overflow: "hidden",
      }}
    >
      <video
        ref={ref}
        src={src}
        poster={near ? poster : undefined}
        width={width}
        height={height}
        muted
        loop={loop}
        playsInline
        autoPlay={eager && !reduced}
        preload={eager ? "metadata" : "none"}
        aria-label={label}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          if (!userPaused && !reduced) onEnded?.()
        }}
        style={{ display: "block", width: "100%", height: "auto", aspectRatio: `${width} / ${height}`, background: "#faf5ee" }}
      >
        {label}
      </video>
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause video" : "Play video"}
        style={{
          position: "absolute",
          right: 10,
          bottom: 10,
          width: 34,
          height: 34,
          borderRadius: 999,
          border: "1px solid rgba(255,255,255,0.5)",
          background: "rgba(31,42,46,0.72)",
          color: "#ffffff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
        }}
      >
        {playing ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="5" y="4" width="5" height="16" rx="1" />
            <rect x="14" y="4" width="5" height="16" rx="1" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M7 4v16l13-8Z" />
          </svg>
        )}
      </button>
    </div>
  )
}
