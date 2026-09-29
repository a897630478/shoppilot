<!-- frontend/src/views/product/ProductListView.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { productsApi, type ProductListItem } from '@/api/products'

const router = useRouter()
const loading = ref(false)
const items = ref<ProductListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const keyword = ref('')
const category = ref<string | null>(null)
const categories = ref<string[]>([])

async function load() {
  loading.value = true
  try {
    const { data } = await productsApi.list({
      page: page.value,
      page_size: pageSize,
      keyword: keyword.value || null,
      category: category.value,
    })
    items.value = data.items
    total.value = data.total
    // 类目选项：从已加载数据聚合（M2 轻量做法，避免后端加接口）
    const set = new Set(categories.value)
    data.items.forEach((it) => { if (it.category) set.add(it.category) })
    categories.value = [...set].sort()
  } catch {
    ElMessage.error('商品列表加载失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}
function goDetail(id: string) {
  router.push(`/products/${id}`)
}
watch(page, load)
onMounted(load)
</script>

<template>
  <div class="product-list">
    <div class="toolbar">
      <el-input
        v-model="keyword" placeholder="搜索商品名称/简介" clearable
        style="width: 280px" :prefix-icon="Search" @keyup.enter="search" @clear="search"
      />
      <el-select v-model="category" placeholder="全部类目" clearable style="width: 160px" @change="search">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button type="primary" @click="search">搜索</el-button>
    </div>

    <div v-loading="loading" class="grid">
      <el-card
        v-for="p in items" :key="p.id" shadow="never" class="card sp-hover"
        @click="goDetail(p.id)"
      >
        <div class="card-inner">
          <img
            v-if="p.image_url"
            :src="p.image_url"
            :alt="p.title"
            class="thumb"
            loading="lazy"
          />
          <div v-else class="thumb thumb--empty">无图</div>
          <div class="card-body">
            <div class="card-title">{{ p.title }}</div>
            <div class="card-meta">
              <span v-if="p.category" class="tag">{{ p.category }}</span>
              <span v-if="p.rating" class="rating">★ {{ p.rating }}</span>
            </div>
            <div class="price-tag">
              <span class="yen">¥</span>
              <span class="num">{{ p.price }}</span>
            </div>
          </div>
        </div>
      </el-card>
      <el-empty v-if="!loading && items.length === 0" description="没有匹配的商品" />
    </div>

    <el-pagination
      v-model:current-page="page" :page-size="pageSize" :total="total"
      layout="prev, pager, next, total" class="pager"
    />
  </div>
</template>

<style scoped>
.product-list { max-width: 1100px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; min-height: 200px; }
.card { cursor: pointer; border-radius: 14px; }
.card :deep(.el-card__body) { padding: 14px; }
.card-inner { display: flex; gap: 14px; }
.thumb {
  width: 88px;
  height: 88px;
  flex-shrink: 0;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid var(--sp-line);
  background: var(--sp-bg);
}
.thumb--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--sp-ink-3);
  font-size: 12px;
}
.card-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.card-title {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
  letter-spacing: -0.01em;
  height: 38px;
  overflow: hidden;
  color: var(--sp-ink);
}
.card-meta { display: flex; justify-content: space-between; margin: 6px 0 10px; color: var(--sp-ink-3); font-size: 12px; }
.tag {
  background: var(--sp-primary-soft);
  color: var(--sp-primary);
  border-radius: 4px;
  padding: 2px 8px;
}
.rating { color: var(--sp-accent); font-weight: 600; }
.pager { margin-top: 20px; justify-content: center; }
</style>
