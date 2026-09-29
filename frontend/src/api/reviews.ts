// frontend/src/api/reviews.ts
import client from './client'

export interface ReviewDimension {
  key: string
  name: string
  score: number
  weight: number
  issues: string[]
  suggestions: string[]
}

export interface ReviewReport {
  report_id: string
  product_id: string
  product_title: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  weighted_score: number | null
  dimensions: ReviewDimension[]
  pros: string[]
  cons: string[]
  summary: string | null
  error_msg: string | null
}

export const reviewsApi = {
  create: (productId: string) =>
    client.post<{ report_id: string; status: string }>('/reviews/reports', { product_id: productId }),
  get: (reportId: string) => client.get<ReviewReport>(`/reviews/reports/${reportId}`),
  latest: (productId: string) =>
    client.get<ReviewReport>('/reviews/reports/latest', { params: { product_id: productId } }),
}
