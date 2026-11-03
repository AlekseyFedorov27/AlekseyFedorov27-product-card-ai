<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { ProductInput } from '../types'

const emit = defineEmits<{ submit: [ProductInput] }>()

const form = reactive<ProductInput>({
  name: '',
  manufacturer: '',
  specs: {},
  description: '',
})

const specsText = ref('{}')
const specsError = ref<string | null>(null)
const touched = reactive({ name: false, manufacturer: false })

const examples: Record<string, ProductInput> = {
  'Манометр DM 02': {
    name: 'Манометр показывающий DM 02',
    manufacturer: 'Манотомь',
    specs: {
      'диапазон измерений': '0–1,6 МПа',
      'класс точности': '1,5',
      'присоединение': 'G1/2',
      'диаметр корпуса': '100 мм',
      'рабочая температура': '−50…+60 °C',
      'степень защиты': 'IP54',
    },
    description:
      'Прибор предназначен для измерения избыточного давления неагрессивных к медным сплавам жидкостей и газов. Применяется в системах отопления, водоснабжения и технологических трубопроводах. Корпус из нержавеющей стали, ударопрочное стекло, встроенный демпфер для защиты от вибрации.',
  },
  'Датчик ДД 100': {
    name: 'Датчик давления ДД 100',
    manufacturer: 'Элемер',
    specs: {
      'диапазон измерений': '0–10 МПа',
      'класс точности': '0,25',
      'выходной сигнал': '4–20 мА',
      'питание': '24 В DC',
      'присоединение': 'M20×1,5',
      'степень защиты': 'IP65',
      'рабочая температура': '−40…+85 °C',
    },
    description:
      'Датчик предназначен для непрерывного преобразования избыточного давления в унифицированный токовый сигнал 4–20 мА. Применяется в системах автоматического контроля и регулирования технологических процессов.',
  },
}

const specsCount = computed(() => {
  if (specsError.value) return 0
  try {
    const parsed = JSON.parse(specsText.value)
    return typeof parsed === 'object' && parsed && !Array.isArray(parsed)
      ? Object.keys(parsed).length
      : 0
  } catch {
    return 0
  }
})

const descriptionShort = computed(
  () => form.description.trim().length > 0 && form.description.trim().length < 30,
)

const validationError = computed<string | null>(() => {
  if (!form.name.trim()) return 'Не заполнено поле «Название»'
  if (!form.manufacturer.trim()) return 'Не заполнено поле «Производитель»'
  if (specsError.value) return specsError.value
  return null
})

const buttonText = computed(() => {
  if (!form.name.trim()) return 'Укажите название'
  if (!form.manufacturer.trim()) return 'Укажите производителя'
  if (specsError.value) return 'Исправьте JSON в характеристиках'
  if (specsCount.value === 0 || form.description.trim().length < 30)
    return 'Сгенерировать черновик (с пометками о неполных данных)'
  return 'Сгенерировать черновик'
})

const canSubmit = computed(() => validationError.value === null)

function validateSpecs() {
  specsError.value = null
  const trimmed = specsText.value.trim()
  if (!trimmed) {
    form.specs = {}
    return
  }
  try {
    const parsed = JSON.parse(trimmed)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      specsError.value = 'Характеристики должны быть объектом {параметр: значение}'
      form.specs = {}
      return
    }
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v !== 'string') {
        specsError.value = `Значение «${k}» должно быть строкой`
        form.specs = {}
        return
      }
      if (!v.trim()) {
        specsError.value = `Значение «${k}» не может быть пустым`
        form.specs = {}
        return
      }
    }
    form.specs = parsed as Record<string, string>
  } catch {
    specsError.value = 'Некорректный JSON в характеристиках'
    form.specs = {}
  }
}

watch(specsText, validateSpecs, { immediate: true })

function loadExample(key: string) {
  const ex = examples[key]
  if (!ex) return
  form.name = ex.name
  form.manufacturer = ex.manufacturer
  form.description = ex.description
  specsText.value = JSON.stringify(ex.specs, null, 2)
  touched.name = touched.manufacturer = false
}


function loadBadExample(kind: 'empty_name' | 'broken_json' | 'short_desc') {
  loadExample('Манометр DM 02')
  if (kind === 'empty_name') {
    form.name = ''
    touched.name = true
  } else if (kind === 'broken_json') {
    specsText.value = '{ "диапазон измерений": "0–1,6 МПа", '
  } else if (kind === 'short_desc') {
    form.description = 'Манометр для давления.'
  }
}

function submit() {
  touched.name = touched.manufacturer = true
  if (!canSubmit.value) return
  emit('submit', {
    name: form.name.trim(),
    manufacturer: form.manufacturer.trim(),
    specs: form.specs,
    description: form.description.trim(),
  })
}
</script>

<template>
  <section class="card">
    <div class="examples">
      <span>Загрузить пример:</span>
      <button
        v-for="(_, key) in examples"
        :key="key"
        type="button"
        class="ghost"
        @click="loadExample(key)"
      >
        {{ key }}
      </button>
    </div>

    <div class="examples">
      <span>Демо ошибок:</span>
      <button type="button" class="ghost warn" @click="loadBadExample('empty_name')">
        Пустое название
      </button>
      <button type="button" class="ghost warn" @click="loadBadExample('broken_json')">
        Битый JSON
      </button>
      <button type="button" class="ghost warn" @click="loadBadExample('short_desc')">
        Короткое описание
      </button>
    </div>

    <label>
      Название
      <input
        v-model="form.name"
        :class="{ invalid: touched.name && !form.name.trim() }"
        @blur="touched.name = true"
      />
      <span v-if="touched.name && !form.name.trim()" class="field-error">
        Поле обязательно
      </span>
    </label>

    <label>
      Производитель
      <input
        v-model="form.manufacturer"
        :class="{ invalid: touched.manufacturer && !form.manufacturer.trim() }"
        @blur="touched.manufacturer = true"
      />
      <span v-if="touched.manufacturer && !form.manufacturer.trim()" class="field-error">
        Поле обязательно
      </span>
    </label>

    <label>
      Характеристики (JSON)
      <textarea
        v-model="specsText"
        rows="8"
        :class="{ invalid: !!specsError }"
      />
      <span v-if="specsError" class="field-error">{{ specsError }}</span>
    </label>

    <label>
      Описание / паспорт
      <textarea
        v-model="form.description"
        rows="5"
        :class="{ 'invalid': descriptionShort }"
      />
      <span v-if="descriptionShort" class="field-hint">
        Описание короче 30 символов — часть характеристик будет помечена «данных нет»
      </span>
    </label>

    <button
      type="button"
      :disabled="!canSubmit"
      :class="{ 'btn-error': !!validationError }"
      @click="submit"
    >
      {{ buttonText }}
    </button>
    <p v-if="validationError" class="btn-hint">
      Данные некорректны — {{ validationError.toLowerCase() }}
    </p>
  </section>
</template>

<style scoped>
.card { background: white; padding: 24px; border-radius: 10px; }
label { display: block; margin: 12px 0; font-weight: 500; font-size: 14px; }
input, textarea {
  display: block; width: 100%; margin-top: 4px;
  padding: 8px; border: 1px solid #d1d5db; border-radius: 6px;
  font-family: inherit; font-size: 14px; box-sizing: border-box;
  transition: border-color .15s;
}
textarea { font-family: 'JetBrains Mono', monospace; }
input.invalid, textarea.invalid { border-color: #f59e0b; background: #fffbeb; }
.field-error { display: block; color: #b91c1c; font-size: 12px; margin-top: 4px; }
.field-hint { display: block; color: #b45309; font-size: 12px; margin-top: 4px; }
.btn-hint { color: #b91c1c; font-size: 13px; margin: 8px 0 0; }
.examples { margin-bottom: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 14px; color: #6b7280; }
.ghost { background: #e5e7eb; color: #1f2937; }
.ghost.warn { background: #fee2e2; color: #b91c1c; }
button.btn-error { background: #ef4444; }
button.btn-error:disabled { background: #fca5a5; }
</style>