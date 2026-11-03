<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { ProductCard } from '../types'

const props = defineProps<{ draft: ProductCard }>()
const emit = defineEmits<{
  approve: [ProductCard]
  reject: [ProductCard, string]
}>()

const isOpen = ref(false)
const feedback = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function openModal() {
  isOpen.value = true
}

function closeModal() {
  isOpen.value = false
}

function submitReject() {
  const trimmed = feedback.value.trim()
  if (!trimmed) return
  emit('reject', props.draft, trimmed)
  feedback.value = ''
  isOpen.value = false
}

function onBackdropKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    closeModal()
  }
}

let prevOverflow = ''
watch(isOpen, async (open) => {
  if (open) {
    prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    textareaRef.value?.focus()
  } else {
    document.body.style.overflow = prevOverflow
  }
})

onBeforeUnmount(() => {
  document.body.style.overflow = prevOverflow
})
</script>

<template>
  <div class="bar">
    <button type="button" class="secondary" @click="openModal">
      🔁 Отправить на доработку
    </button>
    <button type="button" @click="emit('approve', props.draft)">
      ✅ Одобрить черновик
    </button>
  </div>

  <Teleport to="body">
    <div
      v-if="isOpen"
      class="backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reject-modal-title"
      tabindex="-1"
      @click.self="closeModal"
      @keydown="onBackdropKeydown"
    >
      <div class="modal">
        <h2 id="reject-modal-title">Что нужно доработать?</h2>
        <p class="hint">
          Опишите правки для LLM. Чем конкретнее — тем лучше результат.
        </p>

        <textarea
          ref="textareaRef"
          v-model="feedback"
          rows="6"
          placeholder="Например: убери из SEO-описания пересказ таблицы характеристик и фразу «расширяет области применения»"
          @keydown.ctrl.enter.prevent="submitReject"
          @keydown.meta.enter.prevent="submitReject"
        />

        <div class="actions">
          <span class="shortcut-hint">Ctrl+Enter — отправить</span>
          <button type="button" class="secondary" @click="closeModal">
            Отмена
          </button>
          <button
            type="button"
            :disabled="!feedback.trim()"
            @click="submitReject"
          >
            Отправить на доработку
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.bar { display: flex; gap: 12px; justify-content: flex-end; margin: 16px 0; }
.secondary { background: #e5e7eb; color: #1f2937; }


.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.55);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  z-index: 1000;
  animation: fade-in 0.12s ease-out;
}


.modal {
  background: white;
  border-radius: 12px;
  padding: 24px;
  width: 100%;
  max-width: 560px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
  animation: pop-in 0.14s ease-out;
}

.modal h2 {
  margin: 0 0 6px;
  font-size: 18px;
  color: #111827;
}

.hint {
  margin: 0 0 14px;
  color: #6b7280;
  font-size: 13px;
}


textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  resize: vertical;
  min-height: 120px;
  transition: border-color 0.12s, box-shadow 0.12s;
}
textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}


.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}

.shortcut-hint {
  margin-right: auto;
  font-size: 12px;
  color: #9ca3af;
}

.modal button {
  font-family: inherit;
  font-size: 14px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #2563eb;
  color: white;
  cursor: pointer;
  transition: opacity 0.15s;
}
.modal button:hover:not(:disabled) { opacity: 0.9; }
.modal button:disabled { opacity: 0.5; cursor: not-allowed; }
.modal button.secondary { background: #e5e7eb; color: #1f2937; }


@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes pop-in {
  from { transform: translateY(8px) scale(0.98); opacity: 0; }
  to   { transform: translateY(0)    scale(1);    opacity: 1; }
}
</style>