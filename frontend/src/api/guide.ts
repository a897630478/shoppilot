// frontend/src/api/guide.ts
import client from './client'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface GuideSessionItem {
  session_id: string
  stage: string
  status: string
  created_at: string | null
  finished_at: string | null
}

export interface GuideRecommendation {
  product_id: string
  title: string
  price: string | null
  reason: string
}

export interface GuideReportResponse {
  session_id: string
  status: string
  summary: string | null
  recommendations: GuideRecommendation[]
}

export interface GuideChatDone {
  current_stage?: string
  total_turns?: number
  is_finished?: boolean
  report?: { summary?: string; recommendations?: Array<{ product_id: string; reason: string }> }
}

export const guideApi = {
  create: (message: string) =>
    client.post<{ session_id: string; opening_message: string; stage: string }>(
      '/guide/sessions', { message }),
  list: () => client.get<{ total: number; items: GuideSessionItem[] }>('/guide/sessions'),
  report: (sessionId: string) => client.get<GuideReportResponse>(`/guide/sessions/${sessionId}/report`),
  // SSE 直连后端（照抄 interview/qa 的 fetch 流解析，绕过 Vite proxy 缓冲）
  chatStream: async (
    sessionId: string,
    message: string,
    token: string,
    handlers: {
      onToken: (t: string) => void
      onDone: (done: GuideChatDone) => void
      onError: (msg: string) => void
    },
  ) => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/guide/sessions/${sessionId}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        handlers.onError(body.detail || `HTTP ${resp.status}`)
        return
      }
      if (!resp.body) {
        handlers.onError('无响应流')
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const evt = JSON.parse(line.slice(5).trim())
            if (evt.type === 'token') handlers.onToken(evt.content ?? '')
            else if (evt.type === 'done') handlers.onDone(evt)
            else if (evt.type === 'error') handlers.onError(evt.message ?? '服务异常')
          } catch { /* 忽略半行 */ }
        }
      }
    } catch (e) {
      handlers.onError(String(e))
    }
  },
}
