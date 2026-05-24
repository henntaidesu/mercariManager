<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    :title="dialogTitle"
    width="640px"
    align-center
    destroy-on-close
    :close-on-click-modal="false"
    class="item-comment-dialog"
  >
    <div v-loading="loading" element-loading-text="正在打开浏览器并捕获商品评论...">
      <template v-if="item">
        <div class="item-card">
          <el-image
            v-if="item.thumbnail"
            :src="item.thumbnail"
            :preview-src-list="[item.thumbnail]"
            :preview-teleported="true"
            fit="cover"
            class="item-thumb"
            referrerpolicy="no-referrer"
          />
          <div class="item-meta">
            <div class="item-name">{{ item.name || '-' }}</div>
            <div class="item-sub">
              <span class="amount">¥{{ formatYen(item.price) }}</span>
              <el-tag
                :type="item.status === 'on_sale' ? 'success' : 'info'"
                size="small"
                effect="light"
                class="status-tag"
              >
                {{ itemStatusLabel(item.status) }}
              </el-tag>
            </div>
            <div v-if="itemUrl" class="item-link">
              <a :href="itemUrl" target="_blank" rel="noopener">{{ itemId }}</a>
            </div>
          </div>
        </div>

        <div class="section-title">
          评论 ({{ comments.length }})
        </div>
        <div v-if="comments.length === 0" class="empty">
          <el-empty description="暂无评论" :image-size="80" />
        </div>
        <div v-else class="comments">
          <div
            v-for="c in commentsAsc"
            :key="c.id"
            :class="['comment-row', isOwn(c) ? 'comment-own' : 'comment-other']"
          >
            <el-avatar :src="c.user_photo" :size="36" class="comment-avatar">
              {{ (c.user_name || '?').slice(0, 1) }}
            </el-avatar>
            <div class="comment-body">
              <div class="comment-head">
                <span class="comment-user">{{ c.user_name || c.user_id || '-' }}</span>
                <span class="comment-time">{{ displayTs(c.created_ms) }}</span>
              </div>
              <div class="comment-text">{{ c.message }}</div>
            </div>
          </div>
        </div>

        <div class="section-title reply-title">回复</div>
        <el-input
          v-model="replyText"
          type="textarea"
          :rows="3"
          maxlength="1000"
          show-word-limit
          :disabled="posting"
        />
      </template>
      <template v-else-if="!loading">
        <el-empty description="尚未捕获到商品评论数据" />
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)" :disabled="busy">关闭</el-button>
        <el-button
          v-if="item"
          :loading="syncing"
          :disabled="posting"
          @click="runSync"
        >
          刷新评论
        </el-button>
        <el-button
          v-if="item"
          type="primary"
          :loading="posting"
          :disabled="!canSubmit"
          @click="onSubmit"
        >
          コメントを送信する
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { notificationsApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  itemId: { type: String, default: '' },
  itemName: { type: String, default: '' },
  accountId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue', 'posted'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const syncing = ref(false)
const posting = ref(false)

const item = ref(null)
const comments = ref([])
const sellerId = ref(null)
const replyText = ref('')

const busy = computed(() => loading.value || syncing.value || posting.value)
const canSubmit = computed(() => !!replyText.value.trim() && !posting.value)

const itemId = computed(() => props.itemId || item.value?.id || '')
const itemUrl = computed(() =>
  itemId.value ? `https://jp.mercari.com/item/${itemId.value}` : '',
)

const dialogTitle = computed(() => {
  if (props.itemName) return `留言详情 · ${props.itemName}`
  if (item.value?.name) return `留言详情 · ${item.value.name}`
  return `留言详情 · ${itemId.value || ''}`
})

const commentsAsc = computed(() => {
  // 后端可能按 created 倒序返回（新→旧）;聊天 UI 习惯按时间正序展示
  const arr = Array.isArray(comments.value) ? [...comments.value] : []
  arr.sort((a, b) => Number(a.created_ms || 0) - Number(b.created_ms || 0))
  return arr
})

function isOwn(c) {
  // 当前账号 (= seller) 自己发的评论
  return sellerId.value && Number(c.user_id) === Number(sellerId.value)
}

function itemStatusLabel(s) {
  const m = {
    on_sale: '在售',
    trading: '交易中',
    sold_out: '已售',
    stop: '已下架',
  }
  return m[s] || s || '-'
}

function formatYen(n) {
  const v = Number(n || 0)
  if (!v) return '0'
  return v.toLocaleString('ja-JP')
}

function displayTs(ms) {
  const n = Number(ms || 0)
  if (!n) return '-'
  const d = new Date(n)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function resetState() {
  item.value = null
  comments.value = []
  sellerId.value = null
  replyText.value = ''
}

function applyResponse(res) {
  if (!res) return
  item.value = res.item || null
  comments.value = Array.isArray(res.comments) ? res.comments : []
  sellerId.value = res.item?.seller_id || null
}

async function runSync() {
  if (!props.itemId) return
  syncing.value = true
  loading.value = true
  try {
    const res = await notificationsApi.itemCommentSync({
      item_id: props.itemId,
      account_id: props.accountId || null,
    })
    applyResponse(res)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '同步评论失败')
  } finally {
    syncing.value = false
    loading.value = false
  }
}

async function onSubmit() {
  const msg = replyText.value.trim()
  if (!msg) return
  posting.value = true
  try {
    const res = await notificationsApi.itemCommentPost({
      item_id: props.itemId,
      account_id: props.accountId || null,
      message: msg,
    })
    ElMessage.success('已发送评论')
    emit('posted', { item_id: props.itemId, message: msg })
    replyText.value = ''
    // 后端在同一浏览器会话内 reload 并重新抓取了 items/get,
    // 把最新评论列表直接随响应返回,不必再次启动浏览器。
    if (res?.item && Array.isArray(res?.comments)) {
      applyResponse(res)
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '发送评论失败')
  } finally {
    posting.value = false
  }
}

async function closeBrowserSilently() {
  // 用户关弹窗后即使 sync/post 还没启动也无害(close 对未运行的会话是 no-op)
  try {
    await notificationsApi.itemCommentClose({
      account_id: props.accountId || null,
    })
  } catch {
    // 忽略;前端只关 UI,后端关浏览器是 best-effort
  }
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
  if (!v) {
    // 触发后端关闭主 profile 浏览器(fire-and-forget)
    closeBrowserSilently()
    resetState()
  }
}

watch(
  () => [props.modelValue, props.itemId],
  async ([open, iid]) => {
    if (!open || !iid) return
    await runSync()
  },
  { immediate: false },
)
</script>

<style scoped>
.item-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-page);
}
.item-thumb {
  width: 72px;
  height: 72px;
  border-radius: 6px;
  flex-shrink: 0;
}
.item-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.item-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
  word-break: break-all;
  line-height: 1.4;
}
.item-sub {
  display: flex;
  align-items: center;
  gap: 8px;
}
.amount {
  font-weight: 600;
  color: var(--el-color-danger);
}
.status-tag {
  flex-shrink: 0;
}
.item-link {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.section-title {
  margin: 16px 0 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.reply-title {
  margin-top: 18px;
}
.empty {
  padding: 8px 0;
}
.comments {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px 2px;
}
.comment-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.comment-own {
  flex-direction: row-reverse;
}
.comment-avatar {
  flex-shrink: 0;
}
.comment-body {
  max-width: 78%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.comment-own .comment-body {
  align-items: flex-end;
}
.comment-head {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.comment-user {
  font-weight: 500;
}
.comment-time {
  color: var(--el-text-color-placeholder);
}
.comment-text {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.comment-own .comment-text {
  background: var(--el-color-primary-light-8);
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
