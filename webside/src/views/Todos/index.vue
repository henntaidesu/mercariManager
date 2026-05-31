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
            <el-tag :type="kindTagType(row)" size="small" effect="light">
              {{ kindLabel(row) }}
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
              <div class="detail-label">{{ t('todos.productType') }}</div>
              <div class="detail-value">{{ inventoryProductType || dash }}</div>
            </div>
            <div v-if="showMercariPhoto" class="detail-photo-wrap">
              <el-image
                :src="mercariImageUrl(detail.photo_url)"
                :preview-src-list="[mercariImageUrl(detail.photo_url)]"
                :preview-teleported="true"
                fit="cover"
                referrerpolicy="no-referrer"
                class="detail-photo"
              />
            </div>

            <!-- 「発送をしてください」：按商品 ID 反查到的本地库存图片与关联订单号 -->
            <div
              v-if="String(currentRow?.title || '').trim() === WAIT_SHIPPING_TITLE"
              class="detail-inv-match"
            >
              <div class="detail-label">{{ t('todos.matchedInventory') }}</div>
              <div v-if="invMatch.loading" class="detail-empty">{{ t('todos.matching') }}</div>
              <div v-else-if="!invMatch.inventory.length" class="detail-empty">{{ t('todos.noInventoryMatch') }}</div>
              <template v-else>
                <div v-for="inv in invMatch.inventory" :key="inv.id" class="detail-inv-card">
                  <div class="detail-inv-images">
                    <el-image
                      v-for="(img, ii) in inv.images"
                      :key="ii"
                      :src="inventoryThumbUrl(img)"
                      :preview-src-list="inv.images"
                      :initial-index="ii"
                      :preview-teleported="true"
                      fit="cover"
                      class="detail-inv-thumb"
                    >
                      <template #error><span class="thumb-fallback">-</span></template>
                    </el-image>
                    <span v-if="!inv.images.length" class="detail-empty">{{ t('todos.noInventoryImage') }}</span>
                  </div>
                  <div class="detail-inv-meta">
                    <span class="detail-inv-id">{{ t('todos.inventoryId') }}: {{ inv.id }}</span>
                    <span v-if="inv.name" class="detail-inv-name"> · {{ inv.name }}</span>
                    <span v-if="inv.warehouse_name || inv.shelf_name" class="detail-inv-loc">
                      {{ [inv.warehouse_name, inv.shelf_name].filter(Boolean).join(' / ') }}
                    </span>
                  </div>
                </div>
              </template>
            </div>
          </section>

          <!-- 包材与出库（待发货时，放在发货之前） -->
          <section v-if="!isReviewedSeller && isWaitShipping" class="detail-section">
            <div class="detail-section-title">{{ t('todos.packagingAndOutbound') }}</div>
            <div class="detail-ship-commit">
              <div class="detail-ship-pack">
                <div class="detail-label">{{ t('orders.packagingName') }}</div>
                <el-select
                  v-for="(row, idx) in shipPackagingRows"
                  :key="idx"
                  v-model="row.item_name"
                  filterable
                  clearable
                  size="small"
                  class="detail-ship-pack-select"
                  :placeholder="t('orders.packagingItemPlaceholder')"
                  @change="onShipPackagingChange"
                >
                  <el-option :label="t('orders.noPackaging')" :value="PACKAGING_ITEM_NONE" />
                  <el-option
                    v-for="item in packagingItemsOptions"
                    :key="item.item_name"
                    :label="`${item.item_name}（${t('orders.stockLabel')}:${Number(item.quantity || 0)}）`"
                    :value="item.item_name"
                  />
                </el-select>
              </div>

              <div class="detail-ship-outbound" v-loading="shipOutbound.loading">
                <div class="detail-label">{{ t('todos.outboundLines') }}</div>
                <el-table
                  v-if="shipOutbound.lines.length"
                  :data="shipOutbound.lines"
                  size="small"
                  border
                >
                  <el-table-column
                    :label="t('todos.outboundLocation')"
                    min-width="140"
                    show-overflow-tooltip
                  >
                    <template #default="{ row: line }">
                      {{ [line.warehouse_name, line.shelf_name, line.shelf_code].filter(Boolean).join(' - ') || dash }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.quantity')" prop="quantity" width="64" align="center" />
                  <el-table-column :label="t('common.status')" width="86" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        :type="Number(line?.is_stocked_out || 0) === 1 ? 'success' : 'info'"
                        size="small"
                      >
                        {{ Number(line?.is_stocked_out || 0) === 1 ? t('orders.stockedOut') : t('orders.pendingStockOut') }}
                      </el-tag>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-else class="detail-empty">{{ t('todos.noOutboundLines') }}</div>
              </div>
            </div>
          </section>

          <section v-if="!isReviewedSeller" class="detail-section">
            <!-- 已发行二维码时：修改发货方式按钮放到标题右上角 -->
            <div class="detail-section-head">
              <div class="detail-section-title">{{ t('todos.section.shipping') }}</div>
              <el-button
                v-if="detail.qr_image_url"
                size="small"
                @click="onReviseShippingAfterQr"
              >
                {{ t('todos.changeShippingMethod') }}
              </el-button>
            </div>
            <!-- 已发行二维码：发货模块只展示二维码 -->
            <template v-if="detail.qr_image_url">
              <div class="detail-qr-wrap">
                <el-image
                  :src="mercariImageUrl(detail.qr_image_url)"
                  :preview-src-list="[mercariImageUrl(detail.qr_image_url)]"
                  :preview-teleported="true"
                  fit="contain"
                  class="detail-qr-img"
                />
              </div>
            </template>
            <!-- 未发行：当前状态 + 选择尺寸 + 修改发货方式 -->
            <template v-else>
              <div class="detail-shipping-status">
                <span class="detail-label">{{ t('todos.currentStatus') }}</span>
                <span class="detail-value">{{ detail.current_shipping_status || dash }}</span>
              </div>
              <div class="detail-shipping-actions">
                <el-button
                  size="default"
                  @click="onClickShippingSizeLocation"
                >
                  {{ t('todos.pickSizeAndLocation') }}
                </el-button>
                <el-button
                  size="default"
                  @click="onClickShippingChangeMethod"
                >
                  {{ t('todos.changeShippingMethod') }}
                </el-button>
              </div>
            </template>
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
      <el-radio-group v-if="shippingOptions.length" v-model="shippingPickedIdx" class="ship-radio-group">
        <div
          v-for="(opt, idx) in shippingOptions"
          :key="`${opt.name}-${idx}`"
          :class="['ship-card', shippingPickedIdx === idx ? 'ship-card-active' : '']"
          @click="onPickShipping(idx)"
        >
          <el-radio :value="idx" class="ship-card-radio">
            <span class="ship-card-radio-label">{{ opt.name }}</span>
          </el-radio>
          <div class="ship-card-content">
            <img
              class="ship-card-img"
              :src="shippingImageUrl(opt.name)"
              :alt="opt.name"
              @error="onShippingImgError"
            />
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
            </div>
          </div>
        </div>
      </el-radio-group>
      <div v-else class="detail-empty">{{ t('todos.noSizeList') }}</div>

      <div v-if="shippingNeedsFacility" class="ship-facility-section">
        <div class="ship-facility-title">{{ t('todos.shippingFacilityTitle') }}</div>
        <!-- 新式：按尺寸下发的发货地卡片（带图标），点击选中 -->
        <div v-if="shippingFacilities.length" class="ship-facility-cards">
          <div
            v-for="fac in shippingFacilities"
            :key="fac.code"
            :class="['ship-facility-card', shippingFacility === fac.code ? 'ship-facility-card-active' : '']"
            @click="shippingFacility = fac.code"
          >
            <img
              class="ship-facility-img"
              :src="facilityImageUrl(fac.img)"
              :alt="fac.label"
              @error="onShippingImgError"
            />
            <span class="ship-facility-label">{{ fac.label }}</span>
          </div>
        </div>
        <!-- 旧式回落：ゆうゆうメルカリ便 邮局/罗森 -->
        <el-radio-group v-else v-model="shippingFacility" class="ship-facility-radio">
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

    <!-- QR 扫描镜像：把有头浏览器的 /qr_code_scanner 摄像头画面镜像到此处 -->
    <el-dialog
      v-model="qrScanVisible"
      :title="t('todos.qrScanTitle')"
      width="720px"
      :close-on-click-modal="false"
      destroy-on-close
      @close="onQrScanDialogClose"
    >
      <div class="qr-scan-hint">{{ t('todos.qrCamHint') }}</div>
      <div class="qr-scan-stage">
        <video
          ref="qrVideoEl"
          class="qr-scan-video"
          autoplay
          playsinline
          muted
        ></video>
        <div v-if="qrCamError" class="qr-scan-error">
          {{ t('todos.cameraOpenFailed') }}: {{ qrCamError }}
        </div>
        <div v-if="qrScanDone" class="qr-scan-done">{{ t('todos.qrScanDone') }}</div>
      </div>
      <template #footer>
        <el-button @click="onQrScanDialogClose">{{ t('common.close') }}</el-button>
        <el-button type="primary" link @click="onOpenMercariPage">{{ t('todos.openMercariPage') }}</el-button>
      </template>
    </el-dialog>

    <!-- 发货二次确认：展示读取到的发送確認符号 / 追跡番号，用户确认后发送通知 -->
    <el-dialog
      v-model="shipConfirmVisible"
      :title="t('todos.shipConfirmTitle')"
      width="460px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="shipConfirmLoading">
        <div v-if="shipConfirmInfo.ok" class="ship-confirm-ok">{{ t('todos.scanReadOk') }}</div>
        <div class="ship-confirm-row">
          <span class="ship-confirm-label">{{ t('todos.postConfirmCode') }}</span>
          <span class="ship-confirm-value">{{ shipConfirmInfo.confirm_code || dash }}</span>
        </div>
        <div class="ship-confirm-row">
          <span class="ship-confirm-label">{{ t('todos.trackingNo') }}</span>
          <span class="ship-confirm-value">{{ shipConfirmInfo.tracking_no || dash }}</span>
        </div>
        <div class="ship-confirm-hint">{{ t('todos.shipConfirmHint') }}</div>
      </div>
      <template #footer>
        <el-button @click="onShipConfirmCancel">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="shipConfirmLoading" @click="onShipConfirmSubmit">
          {{ t('todos.shipConfirmSubmit') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 修改发货方式：下拉选择配送方式 → 点「変更する」 -->
    <el-dialog
      v-model="changeMethodVisible"
      :title="t('todos.changeMethodTitle')"
      width="460px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="changeMethodLoading">
        <div class="detail-label" style="margin-bottom: 8px">{{ t('todos.changeMethodPick') }}</div>
        <el-select v-model="changeMethodPicked" style="width: 100%" :placeholder="t('todos.changeMethodPick')">
          <el-option
            v-for="opt in changeMethodOptions"
            :key="opt.value"
            :label="opt.label"
            :value="String(opt.value)"
          />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="changeMethodVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="changeMethodLoading"
          :disabled="!changeMethodPicked"
          @click="onConfirmChangeShippingMethod"
        >
          {{ t('todos.changeMethodSubmit') }}
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
