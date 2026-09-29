// frontend/src/api/products.ts
import client from './client'

export interface ProductListItem {
  id: string
  title: string
  category: string | null
  price: string
  currency: string
  rating: number | null
  image_url: string | null
}

export interface ProductDetail extends ProductListItem {
  description: string | null
  params: Record<string, unknown>
  url: string
  source: string
  review_count: number
}

export interface ProductListResponse {
  total: number
  items: ProductListItem[]
}

export const productsApi = {
  list: (params: { page?: number; page_size?: number; category?: string | null; keyword?: string | null }) =>
    client.get<ProductListResponse>('/products', { params }),
  detail: (id: string) => client.get<ProductDetail>(`/products/${id}`),
}
