// frontend/src/api/service.ts
import client from './client'

export type TicketType = 'logistics' | 'refund' | 'exchange'

export interface TicketCreateReq {
  order_id: string
  ticket_type: TicketType
  reason: string
}

export interface TicketItem {
  id: string
  order_id: string
  product_title: string
  ticket_type: TicketType
  reason: string
  status: 'pending' | 'processing' | 'resolved' | 'rejected'
  needs_review: boolean
  ai_result: {
    reply?: string
    suggestion?: string
    confidence?: number
    operator_comment?: string
    operator_action?: string
    error?: string
  } | null
  created_at: string | null
  reviewed_at: string | null
}

export const serviceApi = {
  create: (data: TicketCreateReq) =>
    client.post<{ ticket_id: string; status: string }>('/service/tickets', data),
  listMine: () => client.get<{ total: number; items: TicketItem[] }>('/service/tickets'),
  get: (id: string) => client.get<TicketItem>(`/service/tickets/${id}`),
  listPending: () => client.get<{ total: number; items: TicketItem[] }>('/service/pending-reviews'),
  review: (id: string, action: 'approve' | 'reject', comment?: string) =>
    client.post<{ ticket_id: string; status: string }>(`/service/tickets/${id}/review`, { action, comment }),
}
