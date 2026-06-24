/**
 * useNotificationWebSocket — 管理后台 WebSocket 通知连接。
 *
 * 连接到 /ws/notifications?token=xxx，接收 alert.triggered.browser
 * 消息并推送到 alerts 数组供 Toast 消费。
 *
 * 自动指数退避重连: 1s, 2s, 4s, 8s, ..., max 30s
 * token 为 null/空时不连接。
 */

import { useCallback, useEffect, useRef, useState } from "react"

export interface AlertPayload {
  rule_id: string
  event_id: string
  title: string
  sentiment: string
  news_value_score: number
  entity_names: string[]
  ts: number
}

export interface WsMessage {
  type: string
  payload?: AlertPayload
}

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000

export function useNotificationWebSocket(token: string | null): {
  alerts: AlertPayload[]
  clearAlert: (eventId: string) => void
  isConnected: boolean
} {
  const [alerts, setAlerts] = useState<AlertPayload[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const retryDelayRef = useRef(INITIAL_RECONNECT_DELAY)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return
    const delay = retryDelayRef.current
    retryTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        retryDelayRef.current = Math.min(delay * 2, MAX_RECONNECT_DELAY)
      }
    }, delay)
  }, [])

  useEffect(() => {
    mountedRef.current = true

    if (!token) {
      setIsConnected(false)
      return
    }

    function connect() {
      if (!mountedRef.current) return

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
      const host = window.location.host
      const url = `${protocol}//${host}/ws/notifications?token=${encodeURIComponent(token!)}`

      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close()
          return
        }
        setIsConnected(true)
        retryDelayRef.current = INITIAL_RECONNECT_DELAY
        console.log("[WS] Connected to notifications")
      }

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg: WsMessage = JSON.parse(event.data)
          if (msg.type === "alert" && msg.payload) {
            setAlerts((prev) => [msg.payload!, ...prev].slice(0, 50))
          }
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = (event: CloseEvent) => {
        setIsConnected(false)
        wsRef.current = null
        if (mountedRef.current && event.code !== 4001) {
          scheduleReconnect()
        }
      }

      ws.onerror = () => {
        // onclose will fire after onerror
      }
    }

    connect()

    return () => {
      mountedRef.current = false
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [token, scheduleReconnect])

  const clearAlert = useCallback((eventId: string) => {
    setAlerts((prev) => prev.filter((a) => a.event_id !== eventId))
  }, [])

  return { alerts, clearAlert, isConnected }
}
