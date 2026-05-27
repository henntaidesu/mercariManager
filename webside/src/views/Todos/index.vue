<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            :placeholder="t('todos.searchPlaceholder')"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.account_id"
            :placeholder="t('todos.accountPlaceholder')"
            clearable
            filterable
            style="min-width: 200px"
            @change="onFilterChange"
          >
            <el-option
              v-for="a in accountOptions"
              :key="a.id"
              :label="a.label"
              :value="a.id"
            />
          </el-select>
          <el-select
            v-model="filters.kind"
            :placeholder="t('todos.todoType')"
            clearable
            filterable
            style="min-width: 200px"
            @change="onFilterChange"
          >
            <el-option
              v-for="k in kindOptions"
              :key="k"
              :label="kindLabel(k)"
              :value="k"
            />
          </el-select>
          <el-checkbox v-model="filters.include_deleted" @change="onFilterChange">
            {{ t('todos.includeDone') }}
          </el-checkbox>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-select
            v-model="globalAccountId"
            :placeholder="t('todos.selectMercariAccount')"
            filterable
            class="sync-account-select"
            :loading="mercariAccountStore.loading"
          >
            <el-option
              v-for="acc in mercariAccountStore.activeAccounts"
              :key="acc.id"
              :label="acc.account_name"
              :value="acc.id"
            />
          </el-select>
          <el-button type="primary" :icon="Download" :loading="syncLoading" :disabled="bulkReviewLoading" @click="runSync">
            {{ t('todos.syncFromMercari') }}
          </el-button>
          <el-button type="success" :loading="bulkReviewLoading" :disabled="syncLoading" @click="runBulkReview">
            {{ t('todos.bulkReview') }}
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe row-key="id">
        <el-table-column :label="t('todos.colImage')" width="80" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.photo_url"
              class="todo-thumb"
              :src="mercariImageUrl(row.photo_url)"
              :preview-src-list="[mercariImageUrl(row.photo_url)]"
              :preview-teleported="true"
              fit="cover"
              referrerpolicy="no-referrer"
              lazy
            >
              <template #error>
                <span class="thumb-fallback">-</span>
              </template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('todos.todoType')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="kindTagType(row.kind)" size="small" effect="light">
              {{ kindLabel(row.kind) }}
            </el-tag>
            <div v-if="row.is_delete" class="row-tag-done">{{ t('todos.done') }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('todos.colTitleMessage')" min-width="320" align="left" header-align="center">
          <template #default="{ row }">
            <div v-if="row.title" class="cell-title">{{ row.title }}</div>
            <div class="cell-message">{{ row.message || '-' }}</div>
            <div v-if="row.item_id" class="cell-itemid">
              <el-link :href="mercariItemUrl(row.item_id)" target="_blank" type="primary" underline="never">
                {{ row.item_id }}
              </el-link>
              <span v-if="row.item_name" class="cell-itemname">{{ row.item_name }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('orders.buyer')" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <div v-if="buyerNameFromMessage(row.message)" class="cell-buyer">{{ buyerNameFromMessage(row.message) }}</div>
            <div v-if="row.sender_id" class="cell-sender-id">ID: {{ row.sender_id }}</div>
            <span v-if="!row.sender_id && !buyerNameFromMessage(row.message)" class="cell-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.time')" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(row.mercari_updated || row.mercari_created) }}</div>
            <div v-if="row.synced_at" class="cell-muted-sm">{{ t('common.sync') }}: {{ displayTs(row.synced_at) }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('onSaleItems.account')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.operate')" width="90" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="onProcess(row)">{{ t('todos.process') }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pagination"
        background
        layout="prev, pager, next, sizes, total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </el-card>

<!-- 交易详情面板：通用的「煤炉数据 → 管理软件」表单 -->
    <el-dialog
      v-model="detailDialogVisible"
      :title="`${t('todos.transactionDetail')}  ${detail.item_id || ''}`"
      width="1080px"
      :close-on-click-modal="false"
      destroy-on-close
      @close="onDetailDialogClose"
    >
      <template #header="{ titleId, titleClass }">
        <div class="detail-header">
          <span :id="titleId" :class="titleClass">{{ t('todos.transactionDetail') }} <code>{{ detail.item_id || '-' }}</code></span>
          <div class="detail-header-actions">
            <el-button size="small" :loading="detailLoading" @click="onDetailRefresh">{{ t('todos.refreshFetch') }}</el-button>
            <el-button size="small" type="primary" link @click="onOpenMercariPage">{{ t('todos.openMercariPage') }}</el-button>
          </div>
        </div>
      </template>

      <div v-loading="detailLoading" class="detail-body">
        <!-- 左栏：商品 / 发送元 / 买家 / 发货 -->
        <div class="detail-col detail-col-left">
          <section class="detail-section">
            <div class="detail-section-title">{{ t('todos.section.product') }}</div>
            <div class="detail-row">
              <div class="detail-label">{{ t('orders.itemName') }}</div>
              <div class="detail-value">
                <el-input
                  v-model="detail.product_name"
                  size="default"
                  :placeholder="t('todos.productNamePlaceholder')"
                  clearable
                />
              </div>
            </div>
            <div class="detail-row">
              <div class="detail-label">{{ t('todos.productId') }}</div>
              <div class="detail-value">
                <el-link :href="mercariItemUrl(detail.item_id)" target="_blank" type="primary" underline="never">
                  {{ detail.item_id || dash }}
                </el-link>
              </div>
            </div>
            <div v-if="detail.photo_url" class="detail-photo-wrap">
              <el-image
                :src="mercariImageUrl(detail.photo_url)"
                :preview-src-list="[mercariImageUrl(detail.photo_url)]"
                :preview-teleported="true"
                fit="cover"
                referrerpolicy="no-referrer"
                class="detail-photo"
              />
            </div>
          </section>

          <section class="detail-section">
            <div class="detail-section-title">{{ t('todos.section.sender') }}</div>
            <div v-if="detail.sender_address" class="detail-block">{{ detail.sender_address }}</div>
            <div v-else class="detail-empty">{{ t('todos.toFetch') }}</div>
          </section>

          <section class="detail-section">
            <div class="detail-section-title">{{ t('orders.buyer') }}</div>
            <div class="detail-buyer">
              <div class="detail-buyer-name">{{ detail.buyer_name || dash }}</div>
              <el-tag v-if="detail.buyer_verified" type="success" size="small" effect="light">{{ t('todos.buyerVerified') }}</el-tag>
              <span v-if="detail.sender_id" class="detail-buyer-id">ID: {{ detail.sender_id }}</span>
            </div>
          </section>

          <section v-if="!isReviewedSeller" class="detail-section">
            <div class="detail-section-title">{{ t('todos.section.shipping') }}</div>
            <div class="detail-shipping-status">
              <span class="detail-label">{{ t('todos.currentStatus') }}</span>
              <span class="detail-value">{{ detail.current_shipping_status || dash }}</span>
            </div>
            <div class="detail-shipping-actions">
              <el-button
                size="default"
                :disabled="!detail.has_size_location_btn"
                @click="onClickShippingSizeLocation"
              >
                {{ t('todos.pickSizeAndLocation') }}
              </el-button>
              <el-button
                size="default"
                :disabled="!detail.has_change_method_btn"
                @click="onClickShippingChangeMethod"
              >
                {{ t('todos.changeShippingMethod') }}
              </el-button>
            </div>
            <div class="detail-empty-hint">{{ t('todos.shippingButtonsHint') }}</div>
          </section>
        </div>

        <!-- 右栏：默认是消息/交流；ReviewedSeller 时切换为取引評価表单 -->
        <div class="detail-col detail-col-right">
          <!-- 取引評価（仅 ReviewedSeller） -->
          <section v-if="isReviewedSeller" class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.reviewTitle') }}</div>
            <div class="detail-empty-hint" style="margin-bottom: 10px">
              {{ t('todos.reviewHint') }}
            </div>
            <el-input
              v-model="detail.review_draft"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 12 }"
              :placeholder="t('todos.reviewPlaceholder')"
              maxlength="140"
              show-word-limit
            />
            <div class="detail-reply-actions">
              <el-button size="small" @click="onResetReviewDefault">{{ t('todos.defaultReview') }}</el-button>
              <el-button
                size="small"
                type="primary"
                :loading="reviewLoading"
                :disabled="!detail.review_draft || !detail.review_draft.trim()"
                @click="onSubmitReview"
              >
                {{ t('todos.submitReviewFinish') }}
              </el-button>
            </div>
          </section>

          <!-- 消息 / 交流（默认） -->
          <section v-else class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.section.messages') }}</div>
            <div v-if="detail.messages && detail.messages.length" class="detail-messages">
              <div
                v-for="(m, i) in detail.messages"
                :key="m.id || `idx-${i}`"
                :class="['detail-msg', m.is_buyer ? 'detail-msg-buyer' : 'detail-msg-self']"
              >
                <div v-if="m.from" class="detail-msg-from">{{ m.from }}<span v-if="!m.is_buyer" class="detail-msg-tag-self">{{ t('todos.sellerTag') }}</span></div>
                <div class="detail-msg-text">{{ m.text }}</div>
                <div class="detail-msg-footer">
                  <span v-if="m.at" class="detail-msg-at">{{ m.at }}</span>
                  <span v-if="m.reaction" class="detail-msg-reaction">{{ emojiFor(m.reaction) }}</span>
                  <!-- 仅在 IncomingMessage（待回复）类型 + 买家消息时显示反应按钮 -->
                  <el-popover
                    v-if="canReactToMessages && m.is_buyer && !m.reaction"
                    :width="280"
                    placement="bottom-start"
                    trigger="click"
                    popper-class="reaction-popover"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="reaction-add-btn"
                        :title="t('todos.addReaction')"
                        :aria-label="t('todos.addReaction')"
                        :disabled="reactionLoading"
                      >
                        <svg viewBox="0 0 24 24" width="18" height="18" class="reaction-add-btn-icon-smile">
                          <path d="M9.21,11a.85.85,0,0,0,.84-.84.84.84,0,0,0-1.68,0A.85.85,0,0,0,9.21,11Z"/>
                          <path d="M14.79,9.29a.84.84,0,0,0-.84.83.84.84,0,1,0,1.68,0A.84.84,0,0,0,14.79,9.29Z"/>
                          <path d="M14.79,12.77H9.21a.7.7,0,0,0-.7.7,3.49,3.49,0,0,0,7,0A.7.7,0,0,0,14.79,12.77ZM12,15.56a2.09,2.09,0,0,1-2-1.39H14A2.09,2.09,0,0,1,12,15.56Z"/>
                          <path d="M12,2A10,10,0,1,0,22,12,10,10,0,0,0,12,2Zm0,18.6A8.6,8.6,0,1,1,20.6,12,8.61,8.61,0,0,1,12,20.6Z"/>
                        </svg>
                        <svg viewBox="0 0 24 24" width="14" height="14" class="reaction-add-btn-icon-plus">
                          <path d="M21,11H13V3a1,1,0,0,0-2,0v8H3a1,1,0,0,0,0,2h8v8a1,1,0,0,0,2,0V13h8a1,1,0,0,0,0-2Z"/>
                        </svg>
                      </button>
                    </template>
                    <div class="reaction-grid">
                      <button
                        v-for="opt in reactionOptions"
                        :key="opt.key"
                        type="button"
                        class="reaction-grid-item"
                        :title="opt.label"
                        :disabled="reactionLoading"
                        @click="onSendReaction(m, opt.key)"
                      >
                        <span class="reaction-grid-emoji">{{ opt.emoji }}</span>
                      </button>
                    </div>
                  </el-popover>
                </div>
              </div>
            </div>
            <div v-else class="detail-empty">{{ t('todos.toFetch') }}</div>

            <div class="detail-reply">
              <el-input
                v-model="detail.reply_draft"
                type="textarea"
                :autosize="{ minRows: 4, maxRows: 8 }"
                :placeholder="t('todos.replyPlaceholder')"
              />
              <div class="detail-reply-actions">
                <el-button size="small" @click="onResetReplyDefault">{{ t('todos.defaultReply') }}</el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="replyLoading"
                  :disabled="!detail.reply_draft || !detail.reply_draft.trim()"
                  @click="onSendReply"
                >
                  {{ t('todos.sendReply') }}
                </el-button>
              </div>
            </div>
          </section>
        </div>
      </div>

      <template #footer>
        <el-button @click="detailDialogVisible = false">{{ t('common.close') }}</el-button>
        <el-button type="primary" :disabled="detailLoading" @click="onDetailSubmit">{{ t('todos.finishProcess') }}</el-button>
      </template>
    </el-dialog>

    <!-- 选择商品尺寸：纯前端硬编码列表，按当前配送方式区分 -->
    <el-dialog
      v-model="shippingDialogVisible"
      :title="t('todos.pickShippingSize')"
      width="780px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div class="shipping-dialog-hint">
        {{ t('todos.currentShippingMethod') }}<strong>{{ detail.shipping_method_name || t('todos.unidentified') }}</strong>
        {{ t('todos.shippingPickHint') }}
      </div>
      <el-radio-group v-if="shippingOptions.length" v-model="shippingPickedIdx" class="ship-radio-group">
        <div
          v-for="(opt, idx) in shippingOptions"
          :key="`${opt.name}-${idx}`"
          :class="['ship-card', shippingPickedIdx === idx ? 'ship-card-active' : '']"
          @click="shippingPickedIdx = idx"
        >
          <el-radio :value="idx" class="ship-card-radio">
            <span class="ship-card-radio-label">{{ opt.name }}</span>
          </el-radio>
          <div class="ship-card-body">
            <div
              v-for="(row, ri) in (opt.rows || [])"
              :key="`row-${ri}`"
              class="ship-card-row"
            >
              <span class="ship-card-label">{{ row[0] }}</span>
              <span :class="['ship-card-value', row[0] === '送料' ? 'ship-card-fee' : '']">{{ row[1] }}</span>
            </div>
            <div
              v-for="(c, ci) in (opt.caveats || [])"
              :key="`cv-${ci}`"
              class="ship-card-caveat"
            >{{ c }}</div>
            <div v-if="opt.auto_finish_no_facility" class="ship-card-note">{{ t('todos.noFacilityNeeded') }}</div>
          </div>
        </div>
      </el-radio-group>
      <div v-else class="detail-empty">{{ t('todos.noSizeList') }}</div>

      <div v-if="shippingNeedsFacility" class="ship-facility-section">
        <div class="ship-facility-title">{{ t('todos.pickupLocation') }}</div>
        <el-radio-group v-model="shippingFacility" class="ship-facility-radio">
          <el-radio value="post_office" border>{{ t('todos.postOffice') }}</el-radio>
          <el-radio value="lawson" border>{{ t('todos.lawson') }}</el-radio>
        </el-radio-group>
      </div>
      <template #footer>
        <el-button @click="shippingDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :disabled="shippingPickedIdx == null"
          :loading="shippingConfirmLoading"
          @click="onConfirmShippingSelection"
        >
          {{ t('todos.confirmAndSend') }}
        </el-button>
      </template>
    </el-dialog>

    <teleport to="body">
      <div
        v-show="syncOverlayVisible"
        class="todos-sync-overlay todos-sync-overlay--dark"
        :class="{ 'todos-sync-overlay--failed': syncOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="todos-sync-overlay__box">
          <el-icon class="is-loading todos-sync-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="todos-sync-overlay__title">{{ syncOverlayTitle }}</div>
          <div class="todos-sync-overlay__step">{{ syncProgressLabel || t('todos.pleaseWait') }}</div>
        </div>
      </div>
    </teleport>

    <SyncOverlay :state="txOverlay.state" />
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<!-- 「从煤炉同步」全屏等待（teleport 到 body，须无 scoped） -->
<style src="./style.global.css"></style>
