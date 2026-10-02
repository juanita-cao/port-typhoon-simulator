import axios from 'axios'
import type { SimResultsResponse, SimulateRequest } from './types'

// In dev, Vite proxy forwards /api → localhost:8000.
// In production, FastAPI serves this file from the same origin, so baseURL = ''.
const client = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '' })

export const api = {
  getResults: () =>
    client.get<SimResultsResponse>('/api/results').then(r => r.data),

  simulate: (req: SimulateRequest) =>
    client.post<SimResultsResponse>('/api/simulate', req).then(r => r.data),
}
