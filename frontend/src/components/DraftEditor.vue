<script setup lang="ts">
import type { ProductCard } from '../types'

const draft = defineModel<ProductCard>({ required: true })
defineProps<{ readonly?: boolean }>()
</script>

<template>
  <section class="card">
    <label>Заголовок (≤ 70)
      <input v-model="draft.title" :readonly="readonly" />
    </label>

    <label>Краткое описание
      <textarea v-model="draft.short_description" :readonly="readonly" rows="2" />
    </label>

    <label>Коммерческий блок (для менеджера)
      <textarea v-model="draft.commercial_block" :readonly="readonly" rows="4" />
    </label>

    <label>SEO-описание (800–1200)
      <textarea v-model="draft.seo_description" :readonly="readonly" rows="12" />
    </label>

    <div class="group">
      <h3>Ключевые особенности</h3>
      <ul>
        <li v-for="(f, i) in draft.key_features" :key="i">
          <input
            :value="f" :readonly="readonly"
            @input="(e) => draft.key_features[i] = (e.target as HTMLInputElement).value"
          />
        </li>
      </ul>
    </div>

    <div class="group">
      <h3>Характеристики</h3>
      <table>
        <thead><tr><th>Параметр</th><th>Значение</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in draft.specifications" :key="k">
            <td>{{ k }}</td>
            <td>{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="group">
      <h3>Применение</h3>
      <ul>
        <li v-for="(a, i) in draft.applications" :key="i">
          <input
            :value="a" :readonly="readonly"
            @input="(e) => draft.applications[i] = (e.target as HTMLInputElement).value"
          />
        </li>
      </ul>
    </div>

    <div class="group">
      <h3>Поисковые запросы</h3>
      <ul>
        <li v-for="(k, i) in draft.search_queries" :key="i">
          <input
            :value="k" :readonly="readonly"
            @input="(e) => draft.search_queries[i] = (e.target as HTMLInputElement).value"
          />
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.card { background: white; padding: 24px; border-radius: 10px; margin: 16px 0; }
label { display: block; margin: 12px 0; font-weight: 500; font-size: 14px; }
input, textarea {
  display: block; width: 100%; margin-top: 4px; padding: 8px;
  border: 1px solid #d1d5db; border-radius: 6px;
  font-family: inherit; font-size: 14px; box-sizing: border-box;
}
input[readonly], textarea[readonly] { background: #f9fafb; }
.group { margin-top: 20px; }
.group h3 { font-size: 14px; margin: 0 0 8px; color: #374151; }
.group ul { list-style: none; padding: 0; margin: 0; }
.group ul li { margin-bottom: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }
th { background: #f9fafb; }
</style>