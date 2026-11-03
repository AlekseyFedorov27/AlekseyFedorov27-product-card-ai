export interface ProductInput {
  name: string
  manufacturer: string
  specs: Record<string, string>
  description: string
}

export interface ProductCard {
  title: string
  short_description: string
  seo_description: string
  commercial_block: string
  key_features: string[]
  specifications: Record<string, string>
  applications: string[]
  search_queries: string[]
}

export type Status =
  | 'idle'
  | 'streaming'
  | 'awaiting_review'
  | 'submitting'
  | 'done'
  | 'error'

export interface StreamEvent {
  event: 'started' | 'node' | 'awaiting_review' | 'done' | 'error'
  thread_id?: string
  node?: string
  draft?: ProductCard
  validation_errors?: string[]
  missing_fields?: string[]
  iteration?: number
  human_approved?: boolean
  message?: string
}

export interface ResumeResult {
  status: 'awaiting_review' | 'done'
  draft: ProductCard
  human_approved: boolean
  validation_errors: string[]
  missing_fields: string[]
  iteration: number
}