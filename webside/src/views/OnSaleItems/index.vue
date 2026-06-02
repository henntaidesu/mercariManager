<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="14" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            :placeholder="t('onSaleItems.searchPlaceholderFull')"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.seller_id"
            :placeholder="t('onSaleItems.sellerPlaceholder')"
            clearable
            filterable
            style="min-width: 200px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in sellerOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="10" class="search-actions">
          <el-tooltip :disabled="!syncLockStore.locked" :content="syncLockStore.label" placement="top">
            <span>
              <el-button type="primary" :icon="Download" :loading="syncLoading || syncLockStore.locked" :disabled="syncLockStore.locked" @click="runSync">
                {{ t('onSaleItems.syncFromMercari') }}
              </el-button>
            </span>
          </el-tooltip>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        :data="displayList"
        v-loading="loading"
        stripe
        row-key="item_id"
        :row-class-name="onSaleRowClassName"
        @expand-change="onTableExpandChange"
      >
        <el-table-column type="expand" width="44">
          <template #default="props">
            <div v-loading="expandSlot(props.row.item_id)?.loading" class="os-expand-wrap">
              <el-table
                :data="expandSlot(props.row.item_id)?.rows || []"
                border
                size="small"
                class="os-expand-table"
                :empty-text="t('onSaleItems.expandEmpty')"
              >
                <el-table-column :label="t('onSaleItems.mgmtId')" width="120" align="center">
                  <template #default="{ row: r }">
                    <div v-if="resolvedMgmtIdsForRow(r).length" class="multi-line-cell">
                      <div v-for="(mid, idx) in resolvedMgmtIdsForRow(r)" :key="`mgmt-${idx}`">{{ mid }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.barcode')" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`bc-${idx}`">{{ ln.barcode || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.productName')" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`name-${idx}`">{{ ln.inventory_name || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.location')" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`loc-${idx}`">{{ ln.location || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.onSaleQuantity')" width="90" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`qty-${idx}`">{{ ln.on_sale_quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.updated')" width="140" align="center">
                  <template #default="{ row: r }">{{ displayTs(r.updated) }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.image')" width="72" align="center" header-align="center" fixed>
          <template #default="{ row }">
            <el-image
              v-if="firstThumb(row)"
              class="os-thumb"
              :src="firstThumb(row)"
              :preview-src-list="thumbPreviewList(row)"
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
        <el-table-column :label="t('onSaleItems.itemId')" prop="item_id" width="150" align="center" header-align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="isOnSaleZeroStockAlert(row)"
              effect="dark"
              placement="top"
              :show-after="100"
              popper-class="on-sale-alert-tooltip-popper"
            >
              <template #content>
                <div class="on-sale-alert-tooltip-title">{{ t('onSaleItems.alertReasonTitle') }}</div>
                <ul class="on-sale-alert-tooltip-list">
                  <li v-for="(reason, i) in onSaleAlertReasons(row)" :key="i">{{ reason }}</li>
                </ul>
              </template>
              <span class="on-sale-alert-id">
                <el-icon class="on-sale-alert-icon"><WarningFilled /></el-icon>
                {{ row.item_id }}
              </span>
            </el-tooltip>
            <span v-else>{{ row.item_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.seller')" prop="seller_name" width="120" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.seller_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.titleColumn')" prop="name" min-width="200" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column :label="t('onSaleItems.priceYen')" width="88" align="center" header-align="center">
          <template #default="{ row }">{{ Number(row.price || 0) }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.statusColumn')" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="onSaleStatusTagType(row.status)" size="small" effect="light">
              {{ onSaleStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.likesComments')" width="76" align="center" header-align="center">
          <template #default="{ row }">{{ row.num_likes ?? 0 }}/{{ row.num_comments ?? 0 }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.pvRecent')" width="100" align="center" header-align="center">
          <template #default="{ row }">{{ row.item_pv ?? 0 }}/{{ row.recent_item_pv ?? 0 }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.searchImpression')" width="108" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="row.search_impression != null">{{ row.search_impression }}/{{ row.recent_search_impression ?? '-' }}</span>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.auction')" width="72" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover v-if="row.auction_info_json" placement="left" :width="280" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">{{ t('onSaleItems.viewBtn') }}</el-button>
              </template>
              <pre class="auction-pre">{{ formatJsonPretty(row.auction_info_json) }}</pre>
            </el-popover>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.created')" width="160" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.created) }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.updated')" width="160" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.updated) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.operate')" width="120" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <el-button
              :type="hasDetailViewable(row) ? 'success' : 'warning'"
              link
              size="small"
              :loading="detailLoadingIds.has(String(row.item_id || '').trim())"
              @click="onDetailActionClick(row)"
            >
              {{ hasDetailViewable(row) ? t('onSaleItems.viewDetail') : t('onSaleItems.fetchDetail') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load"
          background
          size="small"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="detailViewVisible"
      :title="t('onSaleItems.detailTitle')"
      width="760px"
      class="on-sale-detail-dialog"
      destroy-on-close
      @closed="onDetailViewClosed"
    >
      <div v-loading="detailViewLoading" class="detail-view-body">
        <template v-if="detailViewBase">
          <div class="detail-section-title">{{ t('onSaleItems.mercariSideInfo') }}</div>
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item :label="t('onSaleItems.itemIdLabel')" :span="1">{{ detailViewBase.item_id || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.statusColumn')" :span="1">
              <el-tag :type="onSaleStatusTagType(detailViewBase.status)" size="small" effect="light">
                {{ onSaleStatusLabel(detailViewBase.status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.titleColumn')" :span="2">{{ detailViewBase.name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.priceJpy')" :span="1">{{ Number(detailViewBase.price || 0) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.seller')" :span="1">
              {{ detailViewBase.seller_name || '-' }}
              <span v-if="detailViewBase.seller_id" class="cell-muted">（{{ detailViewBase.seller_id }}）</span>
            </el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.mercariUpdated')" :span="1">{{ displayTs(detailViewBase.updated) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.localSynced')" :span="1">{{ displayTs(detailViewBase.synced_at) }}</el-descriptions-item>
          </el-descriptions>

          <div class="detail-section-title">{{ t('onSaleItems.listingDescription') }}</div>
          <div v-if="detailListingBodyText" class="detail-listing-body-wrap">
            <el-input
              type="textarea"
              :model-value="detailListingBodyText"
              readonly
              :autosize="{ minRows: 10, maxRows: 22 }"
            />
          </div>
          <el-empty v-else :description="t('onSaleItems.descEmpty')" :image-size="48" />

          <div class="detail-section-title">{{ t('onSaleItems.linkedProductImages') }}</div>
          <div v-if="detailLinkedImageGroups.length" class="detail-img-groups">
            <div v-for="grp in detailLinkedImageGroups" :key="grp.management_id" class="detail-img-group">
              <div class="detail-img-group__label">
                {{ t('onSaleItems.mgmtIdLabel') }}: {{ grp.management_id }}
                <span v-if="grp.inventory_name" class="cell-muted">（{{ grp.inventory_name }}）</span>
              </div>
              <div class="detail-img-group__list">
                <el-image
                  v-for="(img, idx) in grp.images"
                  :key="idx"
                  class="detail-linked-img"
                  :src="img.thumb"
                  :preview-src-list="grp.previewList"
                  :initial-index="idx"
                  fit="cover"
                  preview-teleported
                  hide-on-click-modal
                  :z-index="4000"
                  referrerpolicy="no-referrer"
                  lazy
                >
                  <template #error><span class="thumb-fallback">-</span></template>
                </el-image>
              </div>
            </div>
          </div>
          <el-empty v-else :description="t('onSaleItems.noLinkedImages')" :image-size="48" />

          <div class="detail-section-title">{{ t('onSaleItems.linkedInventoryDetail') }}</div>
          <el-table
            v-if="detailInventoryLines.length"
            :data="detailInventoryLines"
            border
            stripe
            size="small"
            max-height="320"
            class="detail-inv-table"
          >
            <el-table-column prop="management_id" :label="t('onSaleItems.mgmtIdLabel')" width="100" align="center" />
            <el-table-column prop="barcode" :label="t('onSaleItems.barcode')" min-width="140" show-overflow-tooltip />
            <el-table-column prop="inventory_name" :label="t('onSaleItems.inventoryName')" min-width="160" show-overflow-tooltip />
            <el-table-column prop="location" :label="t('onSaleItems.location')" min-width="140" show-overflow-tooltip />
            <el-table-column prop="on_sale_quantity" :label="t('onSaleItems.onSaleQuantity')" width="88" align="center" />
          </el-table>
          <el-empty v-else :description="t('onSaleItems.invLinesEmpty')" :image-size="56" />
        </template>
      </div>
      <template #footer>
        <div class="detail-footer">
          <div class="detail-footer__left">
            <el-button
              v-if="detailViewBase"
              type="primary"
              plain
              :loading="detailLoadingIds.has(String(detailViewBase.item_id || '').trim())"
              @click="detailViewRefreshFromMercari"
            >
              {{ t('onSaleItems.refetchFromMercari') }}
            </el-button>
          </div>
          <div class="detail-footer__right">
            <el-button @click="detailViewVisible = false">{{ t('common.close') }}</el-button>
            <el-button
              v-if="detailViewBase"
              type="primary"
              @click="openReviseDialog"
            >
              {{ t('onSaleItems.editListing') }}
            </el-button>
            <el-button
              v-if="detailViewBase"
              type="danger"
              plain
              :loading="deleteItemLoading"
              @click="deleteMercariItemFromDetail"
            >
              {{ t('onSaleItems.deleteItem') }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="reviseDialogVisible"
      :title="t('onSaleItems.reviseDialogTitle')"
      width="600px"
      append-to-body
      destroy-on-close
      class="on-sale-revise-dialog"
    >
      <el-form label-width="110px" class="on-sale-revise-form">
        <el-form-item :label="t('onSaleItems.titleColumn')">
          <el-input
            v-model="reviseForm.name"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="80"
            show-word-limit
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('onSaleItems.listingDescriptionEdit')">
          <el-input
            v-model="reviseForm.listing_description"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 18 }"
            maxlength="900"
            show-word-limit
          />
        </el-form-item>
        <el-form-item :label="t('onSaleItems.priceLabel')">
          <el-input-number
            v-model="reviseForm.price"
            :min="0"
            :precision="0"
            :controls="false"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item v-if="reviseDescCipher" :label="t('onSaleItems.secretCodeLabel')">
          <el-input :model-value="reviseDescCipher" disabled />
        </el-form-item>
        <!-- 出品方式：稍后接入 -->
      </el-form>
      <template #footer>
        <el-button @click="reviseDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="reviseSaving" @click="submitReviseDetail">
          {{ t('onSaleItems.submitRevise') }}
        </el-button>
      </template>
    </el-dialog>

    <teleport to="body">
      <div
        v-show="syncOverlayVisible"
        class="on-sale-sync-overlay on-sale-sync-overlay--dark"
        :class="{ 'on-sale-sync-overlay--failed': syncOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="on-sale-sync-overlay__box">
          <el-icon class="is-loading on-sale-sync-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="on-sale-sync-overlay__title">{{ syncOverlayTitle }}</div>
          <div class="on-sale-sync-overlay__step">{{ syncProgressLabel || t('onSaleItems.pleaseWait') }}</div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<style src="./style.global.css"></style>
