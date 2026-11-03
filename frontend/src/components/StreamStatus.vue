<script setup lang="ts">
defineProps<{ node: string }>()

const nodes = [
  { key: 'prepare_input', label: 'Анализ входных данных' },
  { key: 'generate_draft', label: 'Генерация черновика (LLM)' },
  { key: 'validate_draft', label: 'Валидация' },
  { key: 'critic', label: 'Критик (LLM-редактор)' },
  { key: 'human_review', label: 'Ожидание проверки' },
]
</script>

<template>
  <div class="status-card">
    <p class="loading">⏳ Работаем…</p>
    <ul>
      <li v-for="n in nodes" :key="n.key" :class="{ active: n.key === node }">
        {{ n.label }}<span v-if="n.key === node">←</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.status-card { background: white; padding: 24px; border-radius: 10px; }
.loading { font-weight: 600; margin: 0 0 12px; }
ul { list-style: none; padding: 0; margin: 0; }
li { padding: 8px 0; color: #9ca3af; }
li.active { color: #2563eb; font-weight: 600; }
</style>