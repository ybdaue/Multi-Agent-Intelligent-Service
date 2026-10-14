"use client"

import { useEffect, useRef } from "react"

const POLL_INTERVAL = 60_000 // 60 秒检测一次

/**
 * 客户端 session 状态监控组件。
 * 轮询检测 session 是否失效，检测到时直接跳转登录页。
 * 具体的提示信息由 proxy.ts 重定向到 /login?reason=xxx 后，
 * 在登录页以遮罩形式展示。
 */
export default function SessionMonitor() {
  const hadSessionRef = useRef(false)

  useEffect(() => {
    fetch("/api/auth/session-status").then((r) => r.json()).then((data) => {
      hadSessionRef.current = data.ok
    }).catch(() => {})

    const id = setInterval(async () => {
      try {
        const res = await fetch("/api/auth/session-status")
        const data = await res.json()

        if (hadSessionRef.current && !data.ok) {
          clearInterval(id)
          window.location.href = "/login"
          return
        }

        if (data.ok) hadSessionRef.current = true
      } catch {
        // 网络错误忽略
      }
    }, POLL_INTERVAL)

    return () => clearInterval(id)
  }, [])

  return null
}