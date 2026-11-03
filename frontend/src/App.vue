<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import InputForm from './components/InputForm.vue'
import StreamStatus from './components/StreamStatus.vue'
import DraftEditor from './components/DraftEditor.vue'
import ApproveBar from './components/ApproveBar.vue'
import { exportMarkdown, resumeDraft, streamDraft } from './useDraftApi'
import type { ProductCard, ProductInput, Status } from './types'

const STREAM_TIMEOUT_MS = 600_000
const RESUME_TIMEOUT_MS = 600_000

const status = ref<Status>('idle')
const currentNode = ref<string>('')
const threadId = ref<string>('')
const draft = ref<ProductCard | null>(null)
const validationErrors = ref<string[]>([])
const missingFields = ref<string[]>([])
const errorMessage = ref<string>('')
const humanApproved = ref<boolean>(false)
const iteration = ref<number>(0)


type ToastKind = 'success' | 'error'
const toast = ref<{ text: string; kind: ToastKind } | null>(null)
let toastTimer: number | null = null

function showToast(text: string, kind: ToastKind = 'success') {
  if (toastTimer !== null) window.clearTimeout(toastTimer)
  toast.value = { text, kind }
  toastTimer = window.setTimeout(() => {
    toast.value = null
    toastTimer = null
  }, 3000)
}

onBeforeUnmount(() => {
  if (toastTimer !== null) window.clearTimeout(toastTimer)
})

function applyDraftEvent(e: {
  draft?: ProductCard
  validation_errors?: string[]
  missing_fields?: string[]
  iteration?: number
  human_approved?: boolean
}) {
  draft.value = e.draft ?? null
  validationErrors.value = e.validation_errors ?? []
  missingFields.value = e.missing_fields ?? []
  iteration.value = e.iteration ?? 0
  humanApproved.value = e.human_approved ?? false
}

async function handleGenerate(input: ProductInput) {
  status.value = 'streaming'
  draft.value = null
  errorMessage.value = ''
  validationErrors.value = []
  missingFields.value = []
  humanApproved.value = false
  iteration.value = 0
  currentNode.value = ''

  try {
    await streamDraft(
      input,
      (event) => {
        switch (event.event) {
          case 'started':
            threadId.value = event.thread_id ?? ''
            break
          case 'node':
            currentNode.value = event.node ?? ''
            break
          case 'awaiting_review':
            applyDraftEvent(event)
            status.value = 'awaiting_review'
            break
          case 'done':
            applyDraftEvent(event)
            if (!event.draft) {
              errorMessage.value = 'LLM не вернула валидный черновик.'
              status.value = 'error'
            } else {
              status.value = 'done'
            }
            break
          case 'error':
            errorMessage.value = event.message ?? 'Неизвестная ошибка'
            status.value = 'error'
            break
        }
      },
      AbortSignal.timeout(STREAM_TIMEOUT_MS),
    )

    if (status.value === 'streaming') {
      errorMessage.value =
        'Сервер закрыл поток без финального ответа. Проверьте логи backend.'
      status.value = 'error'
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      errorMessage.value = `Превышено время ожидания (${STREAM_TIMEOUT_MS / 1000} с).`
    } else {
      errorMessage.value = String(e)
    }
    status.value = 'error'
  }
}

async function handleApprove(edited: ProductCard, approved: boolean, feedback = '') {
  if (!threadId.value) return
  status.value = 'submitting'
  errorMessage.value = ''
  try {
    const result = await resumeDraft(
      threadId.value,
      approved,
      edited,
      feedback,
      AbortSignal.timeout(RESUME_TIMEOUT_MS),
    )
    draft.value = result.draft
    validationErrors.value = result.validation_errors ?? []
    missingFields.value = result.missing_fields ?? []
    humanApproved.value = result.human_approved
    iteration.value = result.iteration ?? 0
    status.value = result.status === 'awaiting_review' ? 'awaiting_review' : 'done'
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      errorMessage.value = `Превышено время ожидания (${RESUME_TIMEOUT_MS / 1000} с).`
    } else {
      errorMessage.value = String(e)
    }
    status.value = 'error'
  }
}

async function copyMarkdown() {
  if (!draft.value) return
  try {
    const md = await exportMarkdown(draft.value)
    await navigator.clipboard.writeText(md)
    showToast('Markdown скопирован в буфер обмена', 'success')
  } catch (e) {
    showToast(`Не удалось скопировать: ${String(e)}`, 'error')
  }
}

function reset() {
  status.value = 'idle'
  currentNode.value = ''
  threadId.value = ''
  draft.value = null
  validationErrors.value = []
  missingFields.value = []
  humanApproved.value = false
  iteration.value = 0
  errorMessage.value = ''
}
</script>

<template>
  <main class="app">
    <header>
      <h1>AI-помощник карточек товаров</h1>
      <p class="subtitle">КИП · B2B-каталог</p>
    </header>

    <InputForm v-if="status === 'idle'" @submit="handleGenerate" />

    <StreamStatus
      v-if="status === 'streaming' || status === 'submitting'"
      :node="currentNode"
    />

    <div v-if="status === 'error'" class="error-box">
      <strong>Ошибка:</strong> {{ errorMessage }}
      <button class="secondary" @click="reset">Вернуться к форме</button>
    </div>

    <template v-if="draft && (status === 'awaiting_review' || status === 'submitting' || status === 'done')">
      <div v-if="missingFields.length" class="warn-box">
        <strong>Отсутствующие данные:</strong>
        <ul><li v-for="f in missingFields" :key="f">{{ f }} — данных нет</li></ul>
      </div>

      <div v-if="validationErrors.length" class="warn-box">
        <strong>Замечания валидатора:</strong>
        <ul><li v-for="e in validationErrors" :key="e">{{ e }}</li></ul>
      </div>

      <div class="iteration-badge">Итерация: {{ iteration }}</div>

      <DraftEditor v-model="draft" :readonly="status === 'done'" />

      <div class="toolbar">
        <button class="secondary" @click="copyMarkdown">📋 Копировать Markdown</button>
      </div>

      <ApproveBar
        v-if="status === 'awaiting_review'"
        :draft="draft"
        @approve="(d) => handleApprove(d, true)"
        @reject="(d, fb) => handleApprove(d, false, fb)"
      />

      <div v-if="status === 'done'" class="done-box" :class="{ 'rejected-box': !humanApproved }">
        <template v-if="humanApproved">
          ✅ Готово. Черновик одобрен (итераций: {{ iteration }}).
        </template>
        <template v-else>
          ⛔ Достигнут лимит итераций. Черновик не одобрен — начните заново.
        </template>
        <button class="secondary" @click="reset">Новый товар</button>
      </div>
    </template>
  </main>

  <Teleport to="body">
    <Transition name="toast">
      <div
        v-if="toast"
        class="toast"
        :class="`toast-${toast.kind}`"
        role="status"
        aria-live="polite"
      >
        <span class="toast-icon">{{ toast.kind === 'success' ? '✅' : '⚠️' }}</span>
        <span>{{ toast.text }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #f3f4f6;
  color: #111827;
  font-size: 15px;
  line-height: 1.5;
}

.app {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 16px 64px;
}

header { margin-bottom: 24px; }
header h1 { font-size: 24px; margin: 0 0 4px; }
.subtitle { margin: 0; color: #6b7280; font-size: 14px; }

button {
  font-family: inherit;
  font-size: 14px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #2563eb;
  color: white;
  cursor: pointer;
  transition: opacity .15s;
}
button:hover:not(:disabled) { opacity: .9; }
button:disabled { opacity: .5; cursor: not-allowed; }
button.secondary { background: #e5e7eb; color: #1f2937; }

.error-box,
.warn-box,
.done-box {
  background: white;
  border-radius: 10px;
  padding: 16px 20px;
  margin: 16px 0;
  border-left: 4px solid;
}
.error-box { border-color: #ef4444; background: #fef2f2; }
.warn-box  { border-color: #f59e0b; background: #fffbeb; }
.done-box  { border-color: #10b981; background: #ecfdf5; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.rejected-box { border-color: #ef4444; background: #fef2f2; }

.error-box strong,
.warn-box strong { display: block; margin-bottom: 8px; }
.warn-box ul { margin: 0; padding-left: 20px; }

.iteration-badge {
  display: inline-block;
  background: #e5e7eb;
  color: #374151;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  margin: 8px 0;
}

.toolbar { display: flex; justify-content: flex-end; margin: 12px 0; }

.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 10px;
  color: white;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  z-index: 2000;
  max-width: calc(100vw - 48px);
  word-break: break-word;
}
.toast-success { background: #10b981; }
.toast-error   { background: #ef4444; }
.toast-icon    { font-size: 16px; }

.toast-enter-active,
.toast-leave-active {
  transition: opacity .2s ease, transform .2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>