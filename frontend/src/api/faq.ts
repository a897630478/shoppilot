// frontend/src/api/faq.ts
import client from './client'

export interface FaqPendingItem {
  id: string
  question: string
  confidence: number
  answer: string | null
  created_at: string | null
}

export const faqApi = {
  listPending: () => client.get<{ total: number; items: FaqPendingItem[] }>('/faq/pending'),
  resolve: (id: string, answer: string) =>
    client.post<{ id: string; status: string }>(`/faq/${id}/resolve`, { answer }),
  dismiss: (id: string) =>
    client.post<{ id: string; status: string }>(`/faq/${id}/dismiss`),
}
