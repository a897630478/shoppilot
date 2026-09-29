// frontend/src/api/orders.ts
import client from './client'

export interface OrderCreateReq {
  product_id: string
  quantity: number
  receiver: string
  address: string
}

export interface OrderCreated {
  id: string
  status: string
  unit_price: string
  total_amount: string
  currency: string
  quantity: number
}

export interface OrderItem {
  id: string
  product_id: string
  product_title: string
  quantity: number
  unit_price: string
  total_amount: string
  currency: string
  receiver: string
  address: string
  status: string
  created_at: string | null
}

export const ordersApi = {
  create: (data: OrderCreateReq) => client.post<OrderCreated>('/orders', data),
  list: () => client.get<{ total: number; items: OrderItem[] }>('/orders'),
  detail: (id: string) => client.get<OrderItem>(`/orders/${id}`),
  pay: (id: string) => client.post<{ id: string; status: string }>(`/orders/${id}/pay`),
}
