<template>
  <div :class="{ 'listing-pick-mode-active': listingPickMode }">
    <!-- 库存统计卡片（全库汇总）；手机端不展示 -->
    <el-card v-if="!isMobile" class="section-card inventory-stats-wrap" shadow="never">
      <el-row :gutter="16" class="stat-row inventory-stat-row">
        <el-col :xs="12" :sm="12" :md="8" :lg="4" v-for="card in inventoryStatCards" :key="card.label">
          <div class="inv-stat-card" :style="{ borderTopColor: card.color }">
            <div class="inv-stat-icon" :style="{ background: card.color + '20', color: card.color }">
              <el-icon size="22"><component :is="card.icon" /></el-icon>
            </div>
            <div class="inv-stat-info">
              <div class="inv-stat-value">{{ inventorySummary[card.key] ?? '-' }}</div>
              <div class="inv-stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="14" class="search-left-group">
          <div class="search-left-row1">
            <el-input v-model="keyword" class="search-input-control" placeholder="搜索商品名称或管理番号" clearable @change="load" prefix-icon="Search" />
            <div class="search-filters-row">
              <el-select v-model="filterCat" class="search-select-control" placeholder="所有游戏分类" clearable @change="load">
                <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-cascader
                v-model="filterWarehousePath"
                :options="warehouseCascaderOptions"
                :props="warehouseCascaderProps"
                :show-all-levels="false"
                class="search-select-control"
                placeholder="仓库 / 货架名称 / 货架号"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="handleFilterWarehouseChange"
              />
              <el-cascader
                v-model="filterProductTypePath"
                :options="productTypeCascaderOptions"
                :props="productTypeCascaderProps"
                :show-all-levels="false"
                class="search-select-control"
                placeholder="商品类型"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="handleFilterProductTypeChange"
              />
              <el-select v-model="filterOwnerUserId" class="search-select-control" placeholder="所有商品归属" clearable @change="load">
                <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
              </el-select>
              <el-checkbox v-model="hideNoWarehouseSlot" class="search-filter-checkbox">隐藏无在库</el-checkbox>
            </div>
          </div>
        </el-col>
        <el-col :xs="24" :md="10" class="search-actions" :class="{ 'search-actions--ios': isIOS }">
          <template v-if="isIOS">
            <template v-if="!listingPickMode">
              <div class="search-actions-ios-row">
                <el-button type="success" @click="openContScan">条码入库</el-button>
              </div>
              <div class="search-actions-ios-row">
                <el-button type="warning" @click="openNoBarcodeEntry">无码入库</el-button>
                <el-button @click="enterListingPickMode()">组合商品</el-button>
              </div>
            </template>
            <template v-else>
              <div class="search-actions-ios-row listing-pick-actions">
                <span class="listing-pick-count">已选 {{ listingPickIds.size }} 条</span>
                <el-button type="primary" :disabled="!listingPickIds.size" @click="confirmListingPick">下一步</el-button>
                <el-button @click="exitListingPickMode">取消选择</el-button>
              </div>
            </template>
          </template>
          <template v-else>
            <template v-if="!listingPickMode">
              <el-button type="success" @click="openContScan">条码入库</el-button>
              <el-button type="warning" @click="openNoBarcodeEntry">无码入库</el-button>
              <el-button @click="enterListingPickMode()">组合商品</el-button>
            </template>
            <template v-else>
              <span class="listing-pick-count">已选 {{ listingPickIds.size }} 条</span>
              <el-button type="primary" :disabled="!listingPickIds.size" @click="confirmListingPick">下一步：创建组合商品</el-button>
              <el-button @click="exitListingPickMode">取消选择</el-button>
            </template>
          </template>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div class="table-scroll">
      <el-table
        :data="pagedList"
        v-loading="loading"
        stripe
        row-key="id"
        :size="isMobile ? 'small' : 'default'"
        :row-class-name="rowClassName"
        @sort-change="onInventorySortChange"
        @expand-change="onInventoryExpandChange"
        @row-click="onTableRowClick"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="inventory-expand-wrap" v-loading="getInventoryExpandSlot(row.id)?.loading">
              <el-table
                v-if="mercariItemIds(row).length"
                :data="getInventoryExpandRows(row)"
                size="small"
                border
                class="inventory-expand-inner-table"
                empty-text="暂无在售商品数据"
              >
                <el-table-column label="商品ID" prop="item_id" min-width="130" align="center" />
                <el-table-column label="标题" prop="name" min-width="220" align="left" show-overflow-tooltip />
                <el-table-column label="卖家" prop="seller_name" min-width="120" align="center" show-overflow-tooltip />
                <el-table-column label="价格¥" width="90" align="center">
                  <template #default="{ row: r }">{{ Number(r.price || 0) }}</template>
                </el-table-column>
                <el-table-column label="状态" width="110" align="center">
                  <template #default="{ row: r }">
                    <el-tag :type="onSaleStatusTagType(r.status)" size="small" effect="light">
                      {{ displayOnSaleStatus(r.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="在售数量" width="90" align="center">
                  <template #default="{ row: r }">{{ Number(r.inventory_on_sale_quantity ?? 0) }}</template>
                </el-table-column>
                <el-table-column label="更新" width="150" align="center">
                  <template #default="{ row: r }">{{ formatUnixTs(r.updated) }}</template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无煤炉商品ID" :image-size="48" />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="管理番号" prop="id" width="100" align="center" header-align="center" />
        <el-table-column label="正面图" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_front || row.image"
              class="order-thumb"
              :src="thumbUrl(row.image_front || row.image)"
              :preview-src-list="[row.image_front || row.image]"
              :hide-on-click-modal="true"
              :preview-teleported="true"
              :z-index="4000"
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
        <el-table-column label="背面图" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_back"
              class="order-thumb"
              :src="thumbUrl(row.image_back)"
              :preview-src-list="[row.image_back]"
              :hide-on-click-modal="true"
              :preview-teleported="true"
              :z-index="4000"
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
        <el-table-column label="商品名称" min-width="130" align="left" header-align="left">
          <template #default="{ row }">
            <el-input
              v-if="isEditing(row, 'name')"
              v-model="editingValue"
              size="small"
              class="inline-input"
              @keyup.enter="saveInlineEdit(row, 'name')"
              @blur="saveInlineEdit(row, 'name')"
            />
            <div v-else class="editable-cell" @click="startInlineEdit(row, 'name')">
              <el-tag v-if="Number(row.is_combined || 0) === 1" size="small" type="success" effect="light">组合</el-tag>
              {{ row.name || '-' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="游戏分类" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-select
              v-if="editingCategoryRowId === row.id"
              :model-value="row.category_id"
              size="small"
              style="width: 100%"
              placeholder="选择分类"
              @change="saveCategoryInline(row, $event)"
              @visible-change="(v) => { if (!v) editingCategoryRowId = null }"
            >
              <el-option label="未分类" :value="null" />
              <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <div v-else class="editable-cell" @click="!listingPickMode && (editingCategoryRowId = row.id)">{{ row.category_name || '未分类' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="商品类型" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-cascader
              v-if="editingProductTypeRowId === row.id"
              :model-value="getInlineProductTypePath(row)"
              :options="productTypeCascaderOptions"
              :props="productTypeCascaderProps"
              :show-all-levels="false"
              size="small"
              class="inventory-inline-select"
              placeholder="选择类型"
              popper-class="product-type-cascader-popper"
              filterable
              clearable
              @change="saveProductTypeInline(row, $event)"
              @visible-change="(v) => { if (!v) editingProductTypeRowId = null }"
            />
            <div v-else class="editable-cell" @click="openProductTypeInline(row)">{{ displayProductTypeName(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="商品归属" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-select
              v-if="editingOwnerRowId === row.id"
              :model-value="row.owner_user_id"
              :ref="(el) => setInlineOwnerSelectRef(row.id, el)"
              size="small"
              class="inventory-inline-select"
              placeholder="选择归属"
              popper-class="inventory-inline-select-popper"
              @change="saveOwnerInline(row, $event)"
              @visible-change="(v) => { if (!v) editingOwnerRowId = null }"
            >
              <el-option label="" :value="null" />
              <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
            </el-select>
            <div v-else class="editable-cell" @click="openOwnerInline(row)">{{ displayOwnerName(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="仓库" min-width="100" align="center" header-align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ row.inv_wh_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="所属货架" min-width="100" align="center" header-align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ row.inv_shelf_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="货架号码" min-width="100" align="center" header-align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ row.inv_shelf_code || '-' }}</template>
        </el-table-column>
        <el-table-column label="单价" prop="price" width="120" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            {{ Math.round(Number(row.price || 0)) }}
          </template>
        </el-table-column>
        <el-table-column label="成本（¥）" prop="cost_cny" width="112" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">{{ formatCostCny(row.cost_cny) }}</template>
        </el-table-column>
        <el-table-column label="库存" prop="quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="quantityTagType(row.quantity)" size="small">
              {{ row.quantity || 0 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="在售" prop="on_sale_quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">{{ Number(row.on_sale_quantity ?? 0) }}</template>
        </el-table-column>
        <el-table-column label="待出" prop="pending_outbound_qty" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag v-if="Number(row.pending_outbound_qty || 0) > 0" type="warning" size="small">
              {{ Number(row.pending_outbound_qty || 0) }}
            </el-tag>
            <span v-else class="cell-muted">{{ Number(row.pending_outbound_qty || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!listingPickMode" label="操作" :width="isMobile ? 140 : 160" align="center" header-align="center" :fixed="isMobile ? false : 'right'">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                size="small"
                type="warning"
                :disabled="Number(row.quantity ?? 0) <= 0"
                @click.stop="openListingFormForRow(row)"
              >出品</el-button>
              <el-button size="small" @click.stop="openDialog(row)">编辑</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-else label="选择" width="64" align="center" header-align="center" :fixed="isMobile ? false : 'right'">
          <template #default="{ row }">
            <el-icon v-if="listingPickIds.has(row.id)" color="#67C23A" :size="20"><Check /></el-icon>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-pagination">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          layout="total, prev, pager, next"
          :total="list.length"
          :pager-count="5"
        />
      </div>
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? '编辑商品' : '新增商品'"
      :width="productEditDialogWidth"
      class="product-dialog"
      destroy-on-close
    >
      <div
        class="product-edit-dialog-layout"
        :class="{ 'product-edit-dialog-layout--combined': showCombinedEditDetail }"
      >
        <div class="product-edit-dialog-layout__form">
      <el-form :model="form" :rules="rules" ref="formRef">
        <!-- 条形码行 -->
        <el-form-item label="条形码" prop="barcode">
          <el-input
            v-model="form.barcode"
            placeholder="条形码（必填）"
            class="listing-field-fullwidth"
            size="large"
            clearable
            :disabled="Boolean(form.id)"
          >
            <template #append>
              <el-button @click="openScanDialog">
                <el-icon><Camera /></el-icon> {{ barcodePickButtonLabel }}
              </el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="商品名称">
          <el-input v-model="form.name" class="listing-field-fullwidth" type="text" clearable />
        </el-form-item>
        <el-form-item label="游戏分类" prop="category_id">
          <div class="product-field-inline">
            <template v-if="!categoryCreateMode">
              <el-select
                v-model="form.category_id"
                clearable
                :filterable="!isIOS"
                placeholder="请选择分类"
                class="product-field-inline__main"
              >
                <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-button type="primary" plain @click="startCreateCategory">新建分类</el-button>
            </template>
            <template v-else>
              <el-input
                v-model="newCategoryName"
                placeholder="输入新分类名称"
                clearable
                class="product-field-inline__main"
                @keyup.enter="confirmCreateCategory"
              />
              <el-button type="primary" @click="confirmCreateCategory">确认</el-button>
              <el-button @click="cancelCreateCategory">取消</el-button>
            </template>
          </div>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="16">
            <el-form-item label="商品类型" prop="product_type_id">
              <el-cascader
                v-model="productTypeCascaderPath"
                :options="productTypeCascaderOptions"
                :props="productTypeCascaderProps"
                :show-all-levels="false"
                clearable
                filterable
                placeholder="请选择商品类型（按1/2/3级分类）"
                class="product-field-inline__main"
                style="width: 100%"
                popper-class="product-type-cascader-popper"
                @change="handleProductTypeCascaderChange"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="单价" prop="price">
              <el-input
                v-model="priceEdit"
                placeholder="整数"
                class="product-price-input"
                inputmode="numeric"
                @blur="applyPriceEditToForm"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="成本（¥）" prop="cost_cny">
          <el-input-number
            v-model="form.cost_cny"
            :min="0"
            :max="99999999"
            :precision="2"
            :step="0.01"
            :controls="false"
            placeholder="人民币，可小数"
            class="product-cost-cny-input"
            style="width: 100%"
            clearable
          />
        </el-form-item>
        <el-form-item label="商品归属" prop="owner_user_id">
          <el-select
            v-model="form.owner_user_id"
            clearable
            :filterable="!isIOS"
            placeholder="请选择归属用户"
            class="product-field-inline__main"
          >
            <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="16">
            <el-form-item label="所属货架" prop="warehouse_id">
              <div class="product-field-inline">
                <el-cascader
                  v-model="warehouseCascaderPath"
                  :options="warehouseCascaderOptions"
                  :props="warehouseCascaderProps"
                  :show-all-levels="false"
                  clearable
                  :filterable="!isIOS"
                  placeholder="请选择：仓库 → 货架名称 → 货架号"
                  class="product-field-inline__main"
                  style="width: 100%"
                  popper-class="product-type-cascader-popper"
                  @change="handleWarehouseCascaderChange"
                />
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="库存数量" prop="quantity">
              <el-input
                v-model="quantityEdit"
                placeholder=""
                class="product-qty-input"
                inputmode="numeric"
                @blur="applyQuantityEditToForm"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <!-- 正面图 / 背面图 -->
        <el-row :gutter="20">
          <el-col :xs="24" :sm="12">
            <el-form-item prop="image_front" style="display:block">
              <div class="img-label-row">
                <div class="img-label">正面图</div>
                <el-button type="primary" plain size="small" @click="triggerProductImageFilePick('front')">上传图片</el-button>
              </div>
              <div class="image-upload-area large" @click="openProductImageSource('front')">
                <img v-if="form.image_front" :src="inventoryFormImageSrc('front')" class="preview-img" />
                <div v-else class="upload-placeholder">
                  <el-icon size="36" color="#4a5a72"><Camera /></el-icon>
                  <div class="upload-tip">{{ formImageUploadTip }}</div>
                </div>
              </div>
              <div
                v-if="noBarcodeEntryMode && !form.id && noBarcodeImgUpload.front.uploading"
                class="nb-inventory-upload-progress"
              >
                <el-progress :percentage="noBarcodeImgUpload.front.percent" :stroke-width="10" />
              </div>
              <input
                ref="fileInputFrontPick"
                type="file"
                accept="image/*"
                style="display:none"
                @change="handleImageUpload($event, 'front')"
              />
              <input
                ref="fileInputFront"
                type="file"
                accept="image/*"
                :capture="isIOS ? 'environment' : undefined"
                style="display:none"
                @change="handleImageUpload($event, 'front')"
              />
              <div class="img-actions">
                <el-button v-if="form.image_front" size="small" type="danger" text @click="clearProductFormImage('front')">移除</el-button>
                <el-button v-if="form.image_front" size="small" type="primary" text @click="openOcr('front')">OCR识别名称</el-button>
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item style="display:block">
              <div class="img-label-row">
                <div class="img-label">背面图（选填）</div>
                <el-button type="primary" plain size="small" @click="triggerProductImageFilePick('back')">上传图片</el-button>
              </div>
              <div class="image-upload-area large" @click="openProductImageSource('back')">
                <img v-if="form.image_back" :src="inventoryFormImageSrc('back')" class="preview-img" />
                <div v-else class="upload-placeholder">
                  <el-icon size="36" color="#4a5a72"><Camera /></el-icon>
                  <div class="upload-tip">{{ formImageUploadTip }}</div>
                </div>
              </div>
              <div
                v-if="noBarcodeEntryMode && !form.id && noBarcodeImgUpload.back.uploading"
                class="nb-inventory-upload-progress"
              >
                <el-progress :percentage="noBarcodeImgUpload.back.percent" :stroke-width="10" />
              </div>
              <input
                ref="fileInputBackPick"
                type="file"
                accept="image/*"
                style="display:none"
                @change="handleImageUpload($event, 'back')"
              />
              <input
                ref="fileInputBack"
                type="file"
                accept="image/*"
                :capture="isIOS ? 'environment' : undefined"
                style="display:none"
                @change="handleImageUpload($event, 'back')"
              />
              <div class="img-actions">
                <el-button v-if="form.image_back" size="small" type="danger" text @click="clearProductFormImage('back')">移除</el-button>
                <el-button v-if="form.image_back" size="small" type="primary" text @click="openOcr('back')">OCR识别名称</el-button>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="出品标题">
          <el-input v-model="form.listing_title" class="listing-field-fullwidth" type="text" clearable />
        </el-form-item>
        <el-form-item label="商品说明">
          <el-input
            v-model="form.listing_body"
            class="listing-field-fullwidth"
            type="textarea"
            :rows="5"
            clearable
          />
        </el-form-item>
        <template v-if="form.id">
          <el-form-item label="煤炉商品ID">
            <div class="mercari-id-editor">
              <div v-for="(_, idx) in mercariIdList" :key="idx" class="mercari-id-row">
                <el-input
                  v-model="mercariIdList[idx]"
                  size="small"
                  placeholder="输入商品ID"
                  class="mercari-id-input"
                  clearable
                />
                <el-button size="small" type="danger" text @click="removeMercariId(idx)">删除</el-button>
              </div>
              <el-button size="small" type="primary" plain @click="addMercariId">+ 添加商品ID</el-button>
            </div>
          </el-form-item>
          <el-form-item label="在售数量">
            <el-input-number v-model="form.on_sale_quantity" :min="0" :max="999999" :step="1" controls-position="right" style="width: 160px" />
          </el-form-item>
        </template>
      </el-form>
        </div>
        <aside
          v-if="showCombinedEditDetail"
          class="product-edit-dialog-layout__aside"
          v-loading="combinedEditDetailLoading"
        >
          <div class="combined-edit-aside-title">组合组成明细</div>
          <p class="combined-edit-aside-sub">
            单套用量如下；当前组合库存 <strong>{{ Number(form.quantity ?? 0) }}</strong> 套。
          </p>
          <div class="combined-edit-aside-list">
            <div
              v-for="row in combinedEditDetailRows"
              :key="row.inventory_id"
              class="combined-edit-aside-item"
            >
              <div class="combined-edit-aside-item__thumb">
                <el-image
                  v-if="row.image_front"
                  class="combined-edit-aside-item__img"
                  :src="thumbUrl(row.image_front)"
                  :preview-src-list="[row.image_front]"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :z-index="4000"
                  fit="cover"
                  referrerpolicy="no-referrer"
                >
                  <template #error>
                    <span class="combined-edit-aside-item__img-fallback">-</span>
                  </template>
                </el-image>
                <div v-else class="combined-edit-aside-item__img-placeholder">无图</div>
              </div>
              <div class="combined-edit-aside-item__body">
                <div class="combined-edit-aside-item__title">
                  管理 {{ row.inventory_id }} · {{ row.name || '—' }}
                </div>
                <div class="combined-edit-aside-item__meta">
                  <span>每套用量 <strong>{{ row.per_combo_quantity }}</strong></span>
                  <span v-if="row.loadError" class="combined-edit-aside-item__err">{{ row.loadError }}</span>
                  <span v-else>当前库存 <strong>{{ row.current_quantity ?? '—' }}</strong></span>
                </div>
              </div>
            </div>
            <div v-if="!combinedEditDetailLoading && combinedEditDetailRows.length === 0" class="combined-edit-aside-empty">
              未解析到组成数据（可能缺少 combined_items 记录）
            </div>
          </div>
        </aside>
      </div>
      <template #footer>
        <div class="product-dialog-footer">
          <div class="product-dialog-footer__left">
            <template v-if="form.id">
              <el-button type="success" @click="openOcrForRow(form)">OCR</el-button>
              <el-popconfirm title="确认删除该商品？" @confirm="remove(form.id); dialogVisible = false">
                <template #reference>
                  <el-button type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </div>
          <div class="product-dialog-footer__right">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button
              type="primary"
              @click="submit"
              :loading="submitting"
              :disabled="inventorySaveBlockedByImageUpload"
            >保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 桌面端正/背面：getUserMedia 预览；先「拍照」预览，再「确认拍照」才写入表单 -->
    <el-dialog
      v-model="productImgCameraVisible"
      :title="productImgCameraSide === 'front' ? '拍摄正面图' : '拍摄背面图'"
      :width="isMobile ? '94vw' : '560px'"
      class="scan-dialog"
      destroy-on-close
      @closed="onProductImgCameraClosed"
    >
      <div class="scan-box">
        <div v-if="inventoryCameraDevices.length > 0" class="camera-device-row">
          <span class="camera-device-label">摄像头</span>
          <el-select
            v-model="productImgCameraSelectId"
            filterable
            placeholder="选择摄像头"
            class="camera-device-select"
            :disabled="Boolean(productImgPreviewUrl) || productImgCapturing"
            @change="onProductImgCameraDeviceChanged"
          >
            <el-option
              v-for="d in inventoryCameraDevices"
              :key="d.deviceId"
              :label="d.label"
              :value="d.deviceId"
            />
          </el-select>
        </div>
        <video
          v-show="!productImgPreviewUrl"
          ref="productImgVideoRef"
          class="scan-video"
          autoplay
          playsinline
          muted
        />
        <img
          v-show="productImgPreviewUrl"
          :src="productImgPreviewUrl || undefined"
          class="scan-video product-img-preview-still"
          alt="预览"
        />
        <div class="scan-tip">
          {{
            productImgPreviewUrl
              ? '确认效果后点击「确认拍照」保存，或「重新拍摄」'
              : '对准商品后点击「拍照」生成预览，满意后再确认'
          }}
        </div>
        <div v-if="nbCameraUploading" class="nb-inventory-upload-progress nb-inventory-upload-progress--camera">
          <el-progress :percentage="nbCameraUploadPercent" :stroke-width="10" />
          <div class="nb-inventory-upload-hint">正在上传图片…</div>
        </div>
      </div>
      <template #footer>
        <template v-if="!productImgPreviewUrl">
          <el-button @click="productImgCameraVisible = false">取消</el-button>
          <el-button type="primary" :loading="productImgCapturing" @click="takeProductImgDraft">拍照</el-button>
        </template>
        <template v-else>
          <el-button @click="retakeProductImg" :disabled="nbCameraUploading">重新拍摄</el-button>
          <el-button type="primary" :loading="productImgCapturing" @click="applyProductImgConfirm">确认拍照</el-button>
        </template>
      </template>
    </el-dialog>

    <SingleListingFormDialog
      v-model="listingDialogVisible"
      :category-mappings="listingCategoryMappings"
      :initial-data="listingSeedData"
      :listing-defaults="listingDefaultsFromServer"
      :is-mobile="isMobile"
      @saved="onListingFormSaved"
    />

    <el-dialog
      v-model="combinedProductDialogVisible"
      title="组合商品"
      :width="isMobile ? '94vw' : '720px'"
      class="product-dialog combined-product-dialog"
      destroy-on-close
    >
      <el-form :model="combinedProductForm" label-width="112px" class="combined-product-form">
        <el-form-item label="商品名称" required>
          <el-input v-model="combinedProductForm.name" placeholder="请输入组合商品名称" clearable />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="组合库存数" required>
              <el-input
                v-model="combinedProductForm.quantity"
                inputmode="numeric"
                placeholder="要生成几套组合商品"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="单价">
              <el-input v-model="combinedProductForm.price" inputmode="numeric" placeholder="组合商品单价" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="成本（¥）">
              <el-input-number
                v-model="combinedProductForm.cost_cny"
                :min="0"
                :max="99999999"
                :precision="2"
                :step="0.01"
                :controls="false"
                placeholder="人民币"
                style="width: 100%"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="组成商品" required>
          <div class="combined-product-items">
            <div v-for="item in combinedProductRows" :key="item.id" class="combined-product-item">
              <div class="combined-product-item__thumb">
                <el-image
                  v-if="item.image_front || item.image"
                  class="combined-product-item__img"
                  :src="thumbUrl(item.image_front || item.image)"
                  :preview-src-list="[item.image_front || item.image]"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :z-index="4000"
                  fit="cover"
                  referrerpolicy="no-referrer"
                >
                  <template #error>
                    <span class="combined-product-item__thumb-fallback">-</span>
                  </template>
                </el-image>
                <div v-else class="combined-product-item__thumb-placeholder">
                  <span>无正面图</span>
                </div>
              </div>
              <div class="combined-product-item__main">
                <div class="combined-product-item__name">
                  管理 {{ item.id }} · {{ item.name || '-' }}
                </div>
                <div class="combined-product-item__meta">
                  当前库存 {{ Number(item.quantity || 0) }}，每套使用
                </div>
              </div>
              <el-input
                v-model="item.combine_quantity"
                class="combined-product-item__qty"
                inputmode="numeric"
                @blur="normalizeCombinedProductItemQty(item)"
              />
            </div>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input
            v-model="combinedProductForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选；留空则商品说明与出品正文均不自动填写"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="combinedProductDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="combinedProductSubmitting" @click="submitCombinedProduct">
          创建组合商品
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="scanVisible"
      title="摄像头扫描条形码"
      :width="isMobile ? '94vw' : '640px'"
      class="scan-dialog"
      @closed="stopScan"
    >
      <div class="scan-box">
        <video ref="videoRef" class="scan-video" autoplay playsinline muted />
        <div class="scan-tip">
          <span v-if="scanning" class="scanning-hint">识别中…</span>
          <span v-else>请将条形码置于画面中央，识别后会自动填充</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="scanVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 拍照扫码降级方案（iOS Safari / 非安全上下文）-->
    <input
      ref="cameraInputRef"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleCameraCapture"
    />

    <!-- ===== 连续扫码对话框 ===== -->
    <el-dialog
      v-model="contScanVisible"
      title="条码入库"
      :width="isMobile ? '94vw' : '580px'"
      class="scan-dialog"
      @closed="stopContScan"
    >
      <!-- 扫码中：显示摄像头（多摄像头时可选设备，选择会记住到本机） -->
      <div v-show="contState === 'scanning'" class="scan-box">
        <div v-if="inventoryCameraDevices.length > 0" class="camera-device-row">
          <span class="camera-device-label">摄像头</span>
          <el-select
            v-model="inventoryCameraSelectId"
            filterable
            placeholder="选择摄像头"
            class="camera-device-select"
            @change="onContCameraDeviceChanged"
          >
            <el-option
              v-for="d in inventoryCameraDevices"
              :key="d.deviceId"
              :label="d.label"
              :value="d.deviceId"
            />
          </el-select>
        </div>
        <video ref="contVideoRef" class="scan-video" autoplay playsinline muted />
        <div class="scan-tip">
          <span v-if="contScanning" class="scanning-hint">识别中…</span>
          <span v-else>将条形码对准摄像头，自动识别</span>
        </div>
      </div>

      <!-- iOS / HTTP 降级：拍照按钮 -->
      <div v-if="contState === 'ios-fallback'" class="ios-fallback-box">
        <el-icon size="50" color="#4a5a72"><Camera /></el-icon>
        <p style="color:#8e9bb3;margin:12px 0">当前环境无法在网页内直接预览摄像头连续扫码。</p>
        <p v-if="contScanNeedsHttpsHint" class="cont-https-hint">
          当前为 <strong>HTTP</strong> 且非 localhost：浏览器不允许网页使用摄像头连续预览，只能选图/拍照。
          若要用摄像头：请用 <strong>https://</strong> 打开本站（开发环境为自签名证书，在浏览器中选「高级 → 继续访问」），或使用 <strong>http://localhost:9600</strong>。
        </p>
        <p style="color:#8e9bb3;margin:12px 0">
          {{ canPickImageWithCamera ? '也可点击下方拍照，或从相册选择条形码图片进行识别。' : '也可点击下方上传条形码图片进行识别。' }}
        </p>
        <el-button type="primary" @click="triggerContCapture">{{ formImageUploadTip }}</el-button>
      </div>

      <!-- 找到商品（须同时有 contProduct，避免二次入库时 contState 仍为 found 但 product 已清空导致渲染报错、弹窗空白） -->
      <div v-if="contState === 'found' && contProduct" class="cont-result">
        <div class="barcode-tag">
          <el-icon><Tickets /></el-icon>
          <span>{{ contBarcode }}</span>
        </div>
        <div class="product-images-row">
          <div v-if="contProduct.image_front" class="result-img-wrap">
            <span class="img-side-label">正面</span>
            <img :src="contProduct.image_front" class="result-img" />
          </div>
          <div v-if="contProduct.image_back" class="result-img-wrap">
            <span class="img-side-label">背面</span>
            <img :src="contProduct.image_back" class="result-img" />
          </div>
          <div v-if="!contProduct.image_front && !contProduct.image_back" class="no-image-placeholder">
            <el-icon size="40" color="#4a5a72"><Picture /></el-icon>
            <p>暂无图片</p>
          </div>
        </div>
        <div class="product-meta">
          <span class="product-meta-name">{{ contProduct.name || '(未命名)' }}</span>
          <el-tag type="info" size="small">当前库存 {{ contProduct.quantity ?? 0 }} 件</el-tag>
          <el-tag size="small" effect="plain">仓库 {{ contProduct.warehouse_name || '未设置' }}</el-tag>
        </div>
        <div class="cont-quantity-row">
          <span class="cont-quantity-label">本次数量</span>
          <el-input-number v-model="contQuantity" :min="1" :max="9999" :step="1" controls-position="right" />
        </div>
        <div class="cont-actions">
          <el-button @click="resumeContScan">继续扫码</el-button>
          <el-button type="primary" size="large" :loading="contConfirming" @click="confirmContAction">
            确认入库 +{{ contQuantity }}
          </el-button>
        </div>
      </div>

      <!-- 未找到商品 -->
      <div v-if="contState === 'notfound'" class="cont-result">
        <div class="barcode-tag">
          <el-icon><Tickets /></el-icon>
          <span>{{ contBarcode }}</span>
        </div>
        <div class="notfound-box">
          <el-icon size="44" color="#e6a23c"><Warning /></el-icon>
          <p>该条形码尚未登记商品</p>
        </div>
        <div class="cont-actions">
          <el-button @click="resumeContScan">继续扫码</el-button>
          <el-button type="primary" @click="openAddFromScan">新增商品</el-button>
        </div>
      </div>

      <template #footer>
        <el-button @click="contScanVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 双 input 轮换：iOS 上同一 file 连续拍照/选图时 change 可能不触发，换节点可稳定再次唤起 -->
    <input
      ref="contCameraRefA"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleContCapture"
    />
    <input
      ref="contCameraRefB"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleContCapture"
    />
    <!-- ===== OCR 框选弹窗 ===== -->
    <el-dialog
      v-model="ocrVisible"
      title="框选文字区域 → OCR识别名称"
      :width="isMobile ? '96vw' : '700px'"
      class="ocr-dialog"
      destroy-on-close
      @opened="initOcrCanvas"
    >
      <div v-if="ocrTargetRow" class="ocr-img-tabs">
        <el-button
          :type="ocrSide === 'front' ? 'primary' : 'default'"
          size="small"
          @click="switchOcrSide('front')"
          :disabled="!getOcrSrc('front')"
        >正面图</el-button>
        <el-button
          :type="ocrSide === 'back' ? 'primary' : 'default'"
          size="small"
          @click="switchOcrSide('back')"
          :disabled="!getOcrSrc('back')"
        >背面图</el-button>
      </div>
      <p class="ocr-hint">在图片上拖动框选要识别的文字区域，松手后自动识别写入商品名称</p>
      <div class="ocr-canvas-wrap" ref="ocrWrapRef">
        <canvas
          ref="ocrCanvasRef"
          class="ocr-canvas"
          @mousedown.prevent="ocrDragStart"
          @mousemove.prevent="ocrDragMove"
          @mouseup.prevent="ocrDragEnd"
          @mouseleave.prevent="ocrDragEnd"
          @touchstart.prevent="ocrDragStart"
          @touchmove.prevent="ocrDragMove"
          @touchend.prevent="ocrDragEnd"
        />
      </div>
      <div v-if="ocrLoading" class="ocr-loading">
        <span class="scanning-hint">识别中，请稍候…</span>
      </div>
      <template #footer>
        <el-button @click="ocrVisible = false">取消</el-button>
      </template>
    </el-dialog>

    <teleport to="body">
      <div
        v-show="listingPostOverlayVisible"
        class="listing-post-overlay listing-post-overlay--dark"
        :class="{ 'listing-post-overlay--failed': listingPostOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="listing-post-overlay__box">
          <el-icon class="is-loading listing-post-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="listing-post-overlay__title">{{ listingPostOverlayTitle }}</div>
          <div class="listing-post-overlay__step">{{ listingPostProgressLabel || '请稍候…' }}</div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import {
  inventoryApi,
  categoryApi,
  warehouseApi,
  authApi,
  scanApi,
  ocrApi,
  transactionApi,
  productTypeCategoryMappingApi,
  onSaleItemApi,
  listingApi,
  configApi
} from '@/api/index.js'
import SingleListingFormDialog from '@/components/SingleListingFormDialog.vue'

const list = ref([])
const loading = ref(false)
/** 表头排序：custom 模式，在 sortedList 中处理 */
const inventorySortProp = ref('')
const inventorySortOrder = ref('') // 'ascending' | 'descending' | ''

const inventorySummary = ref({})
const inventoryStatCards = [
  { key: 'total_inventory', label: '库存条目', icon: 'Goods', color: '#409EFF' },
  { key: 'total_quantity', label: '总库存量', icon: 'Box', color: '#E6A23C' },
  { key: 'today_in', label: '今日入库', icon: 'Top', color: '#67C23A' },
  { key: 'today_out', label: '今日出库', icon: 'Bottom', color: '#F56C6C' },
]
const onSaleStatusMap = {
  on_sale: { label: '出售中', tag: 'success' },
  stop: { label: '暂停出售', tag: 'warning' },
  trading: { label: '交易中', tag: 'primary' },
  wait_payment: { label: '待支付', tag: 'warning' },
  wait_shipping: { label: '待发货', tag: 'warning' },
  wait_review: { label: '待评价', tag: 'primary' },
  sold_out: { label: '已售完', tag: 'info' },
  done: { label: '已完成', tag: 'success' },
  cancelled: { label: '已取消', tag: 'info' },
  cancel_request: { label: '取消申请中', tag: 'danger' },
  deleted: { label: '已删除', tag: 'danger' },
  private: { label: '非公开', tag: 'info' },
  pending: { label: '待处理', tag: 'info' },
}
const categories = ref([])
const warehouses = ref([])
const productTypes = ref([])
const ownerUsers = ref([])
const keyword = ref('')
const filterCat = ref(null)
const filterWarehouse = ref(null)
const filterWarehousePath = ref([])
const filterProductType = ref(null)
const filterProductTypePath = ref([])
const filterOwnerUserId = ref(null)
/** localStorage：是否隐藏「库存数量为 0」的条目（与「隐藏无在库」勾选一致） */
const HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY = 'mercari.inventory.hideNoWarehouseSlot'
function readHideNoWarehouseSlotPreference() {
  try {
    const raw = localStorage.getItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY)
    if (raw === '0' || raw === 'false') return false
    if (raw === '1' || raw === 'true') return true
  } catch {
    /* ignore */
  }
  return true
}
/** 默认开启（不展示 quantity=0）；写入 localStorage；watch 内会立即重新拉取列表 */
const hideNoWarehouseSlot = ref(readHideNoWarehouseSlotPreference())
const currentPage = ref(1)
const pageSize = 15
const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()
const fileInputFront = ref()
const fileInputBack = ref()
/** 标签旁「上传图片」：不带 capture，便于从相册/文件选择 */
const fileInputFrontPick = ref()
const fileInputBackPick = ref()
/** 编辑弹窗：桌面端摄像头拍正/背面 */
const productImgCameraVisible = ref(false)
const productImgCameraSide = ref('front')
const productImgVideoRef = ref()
const productImgPreviewUrl = ref(null)
const productImgCapturing = ref(false)
const productImgCameraSelectId = ref('')
let productImgStream = null
const listingDialogVisible = ref(false)
const listingSeedData = ref(null)
/** 系统页「出品默认值」，打开出品弹窗时与 seed 合并（与 SingleListingFormDialog 字段一致） */
const listingDefaultsFromServer = ref({
  shipping_from_area_id: null,
  shipping_method: null,
  shipping_payer: null,
  shipping_days: null,
  meilu_account_id: null
})
/** 组合商品创建弹窗 */
const combinedProductDialogVisible = ref(false)
const combinedProductSubmitting = ref(false)
const combinedProductRows = ref([])
const combinedProductForm = ref({
  name: '',
  quantity: 1,
  price: 0,
  cost_cny: null,
  description: ''
})
/** 组合商品「在列表中选择」模式 */
const listingPickMode = ref(false)
/** 已选中的库存 id 集合 */
const listingPickIds = ref(new Set())
const listingCategoryMappings = ref([])
const noBarcodeEntryMode = ref(false)
/** 无码入库且新建：选图后立即上传服务器，保存时只提交 /imges/ 路径 */
const isNoBarcodeNewInventory = computed(
  () => Boolean(noBarcodeEntryMode.value && !form.value.id)
)
const noBarcodeImgUpload = ref({
  front: { uploading: false, percent: 0 },
  back: { uploading: false, percent: 0 },
})
const nbCameraUploading = ref(false)
const nbCameraUploadPercent = ref(0)
/** 无码新建：各侧正在进行的 multipart 请求，移除/重选时中止 */
const noBarcodeUploadAbortBySide = { front: null, back: null }
/** 库存表单图片上传上限（与后端 save_upload_image 默认一致） */
const MAX_UPLOAD_IMAGE_BYTES = 25 * 1024 * 1024
/** WebDriver 出品自动化：全屏等待与步骤文案（与 progress_job_id 轮询同步） */
const listingPostOverlayVisible = ref(false)
const listingPostOverlayTitle = ref('正在上架')
const listingPostOverlayFailed = ref(false)
const listingPostProgressLabel = ref('')
let listingPostProgressTimer = null
const productTypeCascaderPath = ref([])
const warehouseCascaderPath = ref([])
const inventoryExpandById = ref({})
const scanVisible = ref(false)
const scanning = ref(false)
const videoRef = ref()
const cameraInputRef = ref()
const isMobile = ref(false)
const isIOS = ref(false)
/** iOS 或存在 getUserMedia 时，file input 可加 capture 走相机；否则纯上传 */
const canPickImageWithCamera = computed(
  () => isIOS.value || typeof navigator.mediaDevices?.getUserMedia === 'function'
)
const formImageUploadTip = computed(() => (canPickImageWithCamera.value ? '点击拍照' : '点击上传'))
const barcodePickButtonLabel = computed(() => (canPickImageWithCamera.value ? '拍照' : '上传'))
const editingCell = ref('')
const editingValue = ref('')
const savingInlineCell = ref('')
const editingCategoryRowId = ref(null)
const editingProductTypeRowId = ref(null)
const editingOwnerRowId = ref(null)
const inlineOwnerSelectMap = new Map()
const newCategoryName = ref('')
/** 编辑弹窗：新建分类时，下拉与输入框同位切换 */
const categoryCreateMode = ref(false)
/** 编辑弹窗库存数量：纯文本输入，blur / 保存时写回 form.quantity */
const quantityEdit = ref('0')
/** 编辑弹窗单价：纯文本整数，blur / 保存时写回 form.price */
const priceEdit = ref('0')

/** 编辑弹窗：煤炉商品ID 列表（一对多） */
const mercariIdList = ref([])

function syncQuantityEditFromForm() {
  quantityEdit.value = String(form.value.quantity ?? 0)
}

function applyQuantityEditToForm() {
  const raw = String(quantityEdit.value ?? '').trim()
  const n = parseInt(raw, 10)
  const v = Number.isNaN(n) ? 0 : Math.max(0, n)
  form.value.quantity = v
  quantityEdit.value = String(v)
}

function syncPriceEditFromForm() {
  priceEdit.value = String(Math.round(Number(form.value.price ?? 0)))
}

function applyPriceEditToForm() {
  const raw = String(priceEdit.value ?? '').trim()
  const n = parseInt(raw, 10)
  const v = Number.isNaN(n) ? 0 : Math.max(0, Math.min(999999999, n))
  form.value.price = v
  priceEdit.value = String(v)
}

function parseMercariIdsRaw(raw) {
  return String(raw || '').trim()
    .split(/[\n,，、\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function syncMercariIdListFromForm() {
  mercariIdList.value = parseMercariIdsRaw(form.value.mercari_item_id)
}

function applyMercariIdListToForm() {
  form.value.mercari_item_id = mercariIdList.value
    .map((s) => String(s || '').trim())
    .filter(Boolean)
    .join(',')
}

function addMercariId() {
  mercariIdList.value.push('')
}

function removeMercariId(idx) {
  mercariIdList.value.splice(idx, 1)
}

// ---- OCR 状态 ----
const ocrVisible = ref(false)
const ocrSide = ref('front')
const ocrTargetRow = ref(null)  // 从列表行直接调用时存储 row
const ocrCanvasRef = ref()
const ocrWrapRef = ref()
const ocrLoading = ref(false)
let _ocrDrawing = false
let _ocrStart = { x: 0, y: 0 }
let _ocrRect = { x: 0, y: 0, w: 0, h: 0 }
let _ocrNativeImg = null
let mediaStream = null
let scanTimer = null

// ---- 连续扫码状态 ----
const contScanVisible = ref(false)
/** 桌面端无 getUserMedia（多为 HTTP）时在降级弹窗内提示改用 HTTPS */
const contScanNeedsHttpsHint = ref(false)
const contState = ref('scanning')   // 'scanning' | 'found' | 'notfound' | 'ios-fallback'
const contBarcode = ref('')
const contProduct = ref(null)
const contQuantity = ref(1)
const contScanning = ref(false)
const contConfirming = ref(false)
const contVideoRef = ref()
const contCameraRefA = ref()
const contCameraRefB = ref()
const contScanMode = ref('stream') // 'stream' | 'fallback'
/** 下次拍照识别点击的 input（与另一路交替，缓解 iOS 重复选择同一 input 不触发 change） */
let contCaptureUseA = true
let contStream = null
let contTimer = null

const SCAN_INTERVAL_MS = 500
const CAMERA_CONSTRAINTS = {
  video: {
    facingMode: { ideal: 'environment' },
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 30, max: 60 }
  },
  audio: false
}

/** 库存页扫码：用户选择的摄像头 deviceId（Windows 等多摄像头场景） */
const INVENTORY_CAMERA_STORAGE_KEY = 'mercari.inventory.preferredCameraDeviceId'
const inventoryCameraDevices = ref([])
const inventoryCameraSelectId = ref('')
const NO_BARCODE_FORM_CACHE_KEY = 'mercari.inventory.noBarcode.lastSelections'

/** 无码入库：商品归属默认用当前登录用户 id（与 /api/auth/login 返回的 user.id 一致） */
function getCurrentAuthUserId() {
  try {
    const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
    const n = Number(u.id)
    return Number.isFinite(n) && n > 0 ? Math.round(n) : null
  } catch {
    return null
  }
}

function toNullableInt(v) {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null
}

function readNoBarcodeFormSelectionsCache() {
  try {
    const raw = localStorage.getItem(NO_BARCODE_FORM_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return {
      category_id: toNullableInt(parsed.category_id),
      product_type_id: toNullableInt(parsed.product_type_id),
      owner_user_id: toNullableInt(parsed.owner_user_id),
      warehouse_id: toNullableInt(parsed.warehouse_id)
    }
  } catch {
    return null
  }
}

function writeNoBarcodeFormSelectionsCache(data) {
  try {
    const payload = {
      category_id: toNullableInt(data?.category_id),
      product_type_id: toNullableInt(data?.product_type_id),
      owner_user_id: toNullableInt(data?.owner_user_id),
      warehouse_id: toNullableInt(data?.warehouse_id)
    }
    localStorage.setItem(NO_BARCODE_FORM_CACHE_KEY, JSON.stringify(payload))
  } catch {
    /* ignore */
  }
}

function readSavedInventoryCameraDeviceId() {
  try {
    const s = localStorage.getItem(INVENTORY_CAMERA_STORAGE_KEY)
    const t = s && String(s).trim()
    return t || null
  } catch {
    return null
  }
}

function writeSavedInventoryCameraDeviceId(deviceId) {
  if (!deviceId) return
  try {
    localStorage.setItem(INVENTORY_CAMERA_STORAGE_KEY, String(deviceId))
  } catch {
    /* ignore */
  }
}

function inventoryCameraBaseVideoConstraints() {
  return {
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 30, max: 60 },
  }
}

/**
 * 按优先级尝试打开摄像头：用户保存的 deviceId → 默认约束（后置等）→ 任意摄像头
 */
async function getInventoryCameraStream(preferredDeviceId = null) {
  const base = inventoryCameraBaseVideoConstraints()
  const attempts = []
  if (preferredDeviceId) {
    attempts.push({ video: { ...base, deviceId: { exact: preferredDeviceId } }, audio: false })
    attempts.push({ video: { ...base, deviceId: { ideal: preferredDeviceId } }, audio: false })
  }
  attempts.push(CAMERA_CONSTRAINTS)
  attempts.push({ video: { ...base }, audio: false })
  attempts.push({ video: true, audio: false })
  let lastErr
  for (const constraints of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints)
    } catch (e) {
      lastErr = e
    }
  }
  throw lastErr
}

/**
 * 刷新可选摄像头列表。部分浏览器在授权前 enumerate 为空或不全；若仍为空可传入当前预览流补一条「当前摄像头」。
 */
async function refreshInventoryCameraDeviceList(fallbackStream = null) {
  if (!navigator.mediaDevices?.enumerateDevices) {
    inventoryCameraDevices.value = []
    return
  }
  const list = await navigator.mediaDevices.enumerateDevices()
  const inputs = list.filter((d) => d.kind === 'videoinput')
  let mapped = inputs.map((d, i) => ({
    deviceId: d.deviceId,
    label: (d.label && String(d.label).trim()) ? d.label : `摄像头 ${i + 1}`,
  }))
  if (!mapped.length && fallbackStream?.getVideoTracks) {
    const track = fallbackStream.getVideoTracks()[0]
    const id = track?.getSettings?.()?.deviceId
    if (id) {
      const lb = track.label && String(track.label).trim()
      mapped = [{ deviceId: id, label: lb || '当前摄像头' }]
    }
  }
  inventoryCameraDevices.value = mapped
}

function syncInventoryCameraSelectFromStream(stream) {
  const id = stream?.getVideoTracks?.()?.[0]?.getSettings?.()?.deviceId
  if (id) inventoryCameraSelectId.value = id
}

async function onContCameraDeviceChanged(deviceId) {
  if (!deviceId || contScanMode.value !== 'stream' || contState.value !== 'scanning') return
  writeSavedInventoryCameraDeviceId(deviceId)
  const videoEl = contVideoRef.value
  if (!videoEl) return
  if (contStream) {
    contStream.getTracks().forEach((t) => t.stop())
    contStream = null
  }
  try {
    contStream = await getInventoryCameraStream(deviceId)
    videoEl.srcObject = contStream
    await new Promise((resolve) => {
      videoEl.onloadedmetadata = resolve
    })
    await refreshInventoryCameraDeviceList(contStream)
    syncInventoryCameraSelectFromStream(contStream)
    const okDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
    if (okDev) writeSavedInventoryCameraDeviceId(okDev)
  } catch {
    ElMessage.error('无法切换到所选摄像头，将尝试默认摄像头')
    try {
      contStream = await getInventoryCameraStream(null)
      videoEl.srcObject = contStream
      await new Promise((resolve) => {
        videoEl.onloadedmetadata = resolve
      })
      await refreshInventoryCameraDeviceList(contStream)
      syncInventoryCameraSelectFromStream(contStream)
      const fbDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
      if (fbDev) writeSavedInventoryCameraDeviceId(fbDev)
    } catch {
      ElMessage.error('无法打开摄像头')
      contScanVisible.value = false
    }
  }
}

const form = ref({
  id: null,
  barcode: '',
  name: '',
  category_id: null,
  product_type_id: null,
  warehouse_id: null,
  price: 0,
  cost_cny: null,
  quantity: 1,
  mercari_item_id: '',
  on_sale_quantity: 0,
  description: '',
  listing_title: '',
  listing_body: '',
  image_front: null,
  image_back: null,
  /** 仅展示：组合商品标记（提交前会从 payload 剔除） */
  is_combined: 0,
  combined_items: null
})

/** 编辑组合商品时右侧「组成明细」 */
const combinedEditDetailLoading = ref(false)
const combinedEditDetailRows = ref([])

const showCombinedEditDetail = computed(
  () => Boolean(form.value?.id) && Number(form.value?.is_combined || 0) === 1
)

const productEditDialogWidth = computed(() => {
  if (isMobile.value) return '96vw'
  if (showCombinedEditDetail.value) return 'min(1080px, 98vw)'
  return '580px'
})

const rules = {
  barcode: [{ required: true, message: '请填写或扫描条形码', trigger: 'blur' }],
  image_front: [
    {
      validator: (_, val, cb) => {
        if (Number(form.value?.is_combined || 0) === 1) return cb()
        return val ? cb() : cb(new Error('请拍摄或上传正面图'))
      },
      trigger: 'change',
    },
  ],
  price: [
    {
      validator: (_, val, cb) => {
        const n = Number(val)
        if (Number.isNaN(n) || n < 0) cb(new Error('单价须为大于等于 0 的数字'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
  cost_cny: [
    {
      validator: (_, val, cb) => {
        if (val == null || val === '') return cb()
        const n = Number(val)
        if (Number.isNaN(n) || n < 0) cb(new Error('成本须为大于等于 0 的数字'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

const productTypeCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

/** 与 productTypeCascaderProps 一致：点击展开子级，悬停不跳转 */
const warehouseCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

function updateViewportState() {
  isMobile.value = window.matchMedia('(max-width: 768px)').matches
  const ua = navigator.userAgent || ''
  const platform = navigator.platform || ''
  isIOS.value = /iPhone|iPad|iPod/i.test(ua) || (platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}
updateViewportState()

// ============ OCR 框选 ============

function getOcrSrc(side) {
  if (ocrTargetRow.value) {
    return side === 'front'
      ? (ocrTargetRow.value.image_front || ocrTargetRow.value.image)
      : ocrTargetRow.value.image_back
  }
  return side === 'front' ? form.value.image_front : form.value.image_back
}

function openOcr(side) {
  ocrTargetRow.value = null
  ocrSide.value = side
  _ocrReset()
  ocrVisible.value = true
}

function openOcrForRow(row) {
  ocrTargetRow.value = row
  // 优先正面，若无则背面
  ocrSide.value = (row.image_front || row.image) ? 'front' : 'back'
  _ocrReset()
  ocrVisible.value = true
}

function switchOcrSide(side) {
  ocrSide.value = side
  _ocrReset()
  initOcrCanvas()
}

function _ocrReset() {
  _ocrNativeImg = null
  _ocrDrawing = false
  _ocrRect = { x: 0, y: 0, w: 0, h: 0 }
}

async function initOcrCanvas() {
  await nextTick()
  const canvas = ocrCanvasRef.value
  const wrap = ocrWrapRef.value
  if (!canvas || !wrap) return
  const src = getOcrSrc(ocrSide.value)
  if (!src) return
  _ocrNativeImg = null
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  await new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      _ocrNativeImg = img
      canvas.width = wrap.clientWidth
      canvas.height = Math.round((img.naturalHeight / img.naturalWidth) * wrap.clientWidth)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      resolve()
    }
    img.onerror = reject
    img.src = src
  }).catch(() => {
    ElMessage.error('图片加载失败，无法进行 OCR')
  })
}

function _ocrGetPos(e) {
  const canvas = ocrCanvasRef.value
  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height
  let clientX, clientY
  if (e.touches && e.touches.length > 0) {
    clientX = e.touches[0].clientX
    clientY = e.touches[0].clientY
  } else if (e.changedTouches && e.changedTouches.length > 0) {
    clientX = e.changedTouches[0].clientX
    clientY = e.changedTouches[0].clientY
  } else {
    clientX = e.clientX
    clientY = e.clientY
  }
  return {
    x: Math.max(0, Math.min(canvas.width, Math.round((clientX - rect.left) * scaleX))),
    y: Math.max(0, Math.min(canvas.height, Math.round((clientY - rect.top) * scaleY))),
  }
}

function _ocrRedraw() {
  const canvas = ocrCanvasRef.value
  if (!canvas || !_ocrNativeImg) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(_ocrNativeImg, 0, 0, canvas.width, canvas.height)
  const { x, y, w, h } = _ocrRect
  if (w > 2 && h > 2) {
    ctx.strokeStyle = '#409EFF'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 3])
    ctx.strokeRect(x, y, w, h)
    ctx.fillStyle = 'rgba(64,158,255,0.12)'
    ctx.fillRect(x, y, w, h)
  }
}

function ocrDragStart(e) {
  _ocrDrawing = true
  _ocrStart = _ocrGetPos(e)
  _ocrRect = { x: _ocrStart.x, y: _ocrStart.y, w: 0, h: 0 }
}

function ocrDragMove(e) {
  if (!_ocrDrawing) return
  const cur = _ocrGetPos(e)
  _ocrRect = {
    x: Math.min(_ocrStart.x, cur.x),
    y: Math.min(_ocrStart.y, cur.y),
    w: Math.abs(cur.x - _ocrStart.x),
    h: Math.abs(cur.y - _ocrStart.y),
  }
  _ocrRedraw()
}

async function ocrDragEnd(e) {
  if (!_ocrDrawing) return
  _ocrDrawing = false
  const cur = _ocrGetPos(e)
  _ocrRect = {
    x: Math.min(_ocrStart.x, cur.x),
    y: Math.min(_ocrStart.y, cur.y),
    w: Math.abs(cur.x - _ocrStart.x),
    h: Math.abs(cur.y - _ocrStart.y),
  }
  _ocrRedraw()
  if (_ocrRect.w < 10 || _ocrRect.h < 10) return
  await _ocrSendRegion()
}

async function _ocrSendRegion() {
  if (!_ocrNativeImg) return
  const { x, y, w, h } = _ocrRect
  const canvas = ocrCanvasRef.value
  const scaleX = _ocrNativeImg.naturalWidth / canvas.width
  const scaleY = _ocrNativeImg.naturalHeight / canvas.height
  const crop = document.createElement('canvas')
  crop.width = Math.round(w * scaleX)
  crop.height = Math.round(h * scaleY)
  crop.getContext('2d').drawImage(
    _ocrNativeImg,
    Math.round(x * scaleX), Math.round(y * scaleY), crop.width, crop.height,
    0, 0, crop.width, crop.height
  )
  const base64 = crop.toDataURL('image/jpeg', 0.95)
  ocrLoading.value = true
  try {
    const res = await ocrApi.ocrRegion(base64)
    if (res?.text) {
      if (ocrTargetRow.value) {
        // 从列表行直接调用：直接保存到后端并更新行数据
        await inventoryApi.update(ocrTargetRow.value.id, { name: res.text })
        ocrTargetRow.value.name = res.text
        ElMessage.success(`识别成功并已保存：${res.text}`)
      } else {
        // 从编辑弹窗调用：写入表单
        form.value.name = res.text
        ElMessage.success(`识别成功：${res.text}`)
      }
      ocrVisible.value = false
    } else {
      ElMessage.warning('未识别到文字，请重新框选更清晰的区域')
    }
  } catch {
    ElMessage.error('OCR 识别失败，请确认后端已安装 easyocr 并已重启服务')
  } finally {
    ocrLoading.value = false
  }
}

function getCellKey(row, field) {
  return `${row.id}:${field}`
}

function isEditing(row, field) {
  return editingCell.value === getCellKey(row, field)
}

function startInlineEdit(row, field) {
  if (listingPickMode.value) return
  editingCell.value = getCellKey(row, field)
  const currentValue = row[field]
  editingValue.value = currentValue === null || currentValue === undefined ? '' : String(currentValue)
}

function normalizeInlineValue(field, rawValue) {
  const value = String(rawValue ?? '').trim()
  if (field === 'name') {
    return value || null
  }
  return value || null
}

function setInlineOwnerSelectRef(rowId, el) {
  if (!el) {
    inlineOwnerSelectMap.delete(rowId)
    return
  }
  inlineOwnerSelectMap.set(rowId, el)
}

function openSelectMenuByMap(map, rowId) {
  nextTick(() => {
    const selectRef = map.get(rowId)
    if (!selectRef) return
    if (typeof selectRef.focus === 'function') {
      selectRef.focus()
    }
    if (typeof selectRef.toggleMenu === 'function') {
      selectRef.toggleMenu()
      setTimeout(() => {
        if (selectRef.expanded !== true && typeof selectRef.toggleMenu === 'function') {
          selectRef.toggleMenu()
        }
      }, 0)
    }
  })
}

function openProductTypeInline(row) {
  if (listingPickMode.value) return
  editingProductTypeRowId.value = row.id
}

function openOwnerInline(row) {
  if (listingPickMode.value) return
  editingOwnerRowId.value = row.id
  openSelectMenuByMap(inlineOwnerSelectMap, row.id)
}

function displayProductTypeName(row) {
  const typeId = row?.product_type_id ?? null
  if (typeId != null) {
    const matched = productTypes.value.find((t) => t.id === typeId)
    if (matched?.name) return matched.name
  }
  const name = row?.product_type_name
  if (name == null) return ''
  const text = String(name).trim()
  return text || ''
}

function displayOwnerName(row) {
  const ownerId = row?.owner_user_id ?? null
  if (ownerId != null) {
    const matched = ownerUsers.value.find((u) => u.id === ownerId)
    if (matched) return matched.display_name || matched.username || ''
  }
  const name = row?.owner_user_name
  if (name == null) return ''
  const text = String(name).trim()
  return text || ''
}

async function saveInlineEdit(row, field) {
  const key = getCellKey(row, field)
  if (editingCell.value !== key || savingInlineCell.value === key) return
  let newValue
  try {
    newValue = normalizeInlineValue(field, editingValue.value)
  } catch (err) {
    ElMessage.warning(err.message || '输入格式不正确')
    editingCell.value = ''
    editingValue.value = ''
    return
  }
  if (row[field] === newValue) {
    editingCell.value = ''
    editingValue.value = ''
    return
  }
  savingInlineCell.value = key
  try {
    await inventoryApi.update(row.id, { [field]: newValue })
    row[field] = newValue
    ElMessage.success('已更新')
  } finally {
    if (editingCell.value === key) {
      editingCell.value = ''
      editingValue.value = ''
    }
    savingInlineCell.value = ''
  }
}

async function saveCategoryInline(row, categoryId) {
  const normalizedCategoryId = categoryId || null
  if ((row.category_id || null) === normalizedCategoryId) {
    editingCategoryRowId.value = null
    return
  }
  try {
    await inventoryApi.update(row.id, { category_id: normalizedCategoryId })
    row.category_id = normalizedCategoryId
    const matched = categories.value.find((c) => c.id === normalizedCategoryId)
    row.category_name = matched?.name || null
    ElMessage.success('游戏分类已更新')
  } finally {
    editingCategoryRowId.value = null
  }
}

async function saveProductTypeInline(row, productTypeId) {
  const picked = Array.isArray(productTypeId) ? productTypeId[productTypeId.length - 1] : null
  const normalized = (picked && String(picked).startsWith('PT:'))
    ? Number(String(picked).slice(3))
    : null
  if ((row.product_type_id || null) === normalized) {
    editingProductTypeRowId.value = null
    return
  }
  try {
    await inventoryApi.update(row.id, { product_type_id: normalized })
    row.product_type_id = normalized
    const matched = productTypes.value.find((t) => t.id === normalized)
    row.product_type_name = matched?.name || ''
    ElMessage.success('商品类型已更新')
  } finally {
    editingProductTypeRowId.value = null
  }
}

function getInlineProductTypePath(row) {
  const typeId = Number(row?.product_type_id)
  if (!Number.isFinite(typeId)) return []
  const path = productTypeTreeMeta.value.idToPath.get(typeId)
  return path ? [...path] : []
}

async function saveOwnerInline(row, ownerUserId) {
  const normalized = ownerUserId || null
  if ((row.owner_user_id || null) === normalized) {
    editingOwnerRowId.value = null
    return
  }
  try {
    await inventoryApi.update(row.id, { owner_user_id: normalized })
    row.owner_user_id = normalized
    const matched = ownerUsers.value.find((u) => u.id === normalized)
    row.owner_user_name = matched ? (matched.display_name || matched.username) : ''
    ElMessage.success('商品归属已更新')
  } finally {
    editingOwnerRowId.value = null
  }
}

function startCreateCategory() {
  categoryCreateMode.value = true
  newCategoryName.value = ''
}

function cancelCreateCategory() {
  categoryCreateMode.value = false
  newCategoryName.value = ''
}

function buildProductTypeOptionsFromMappings(mappings) {
  const seen = new Set()
  const out = []
  for (const m of (mappings || [])) {
    const idRaw = String(m?.mapping_id ?? '').trim()
    const name = String(m?.product_type ?? '').trim()
    if (!idRaw || !name) continue
    const id = Number(idRaw)
    if (!Number.isFinite(id) || seen.has(id)) continue
    seen.add(id)
    out.push({ id, name })
  }
  return out
}

function ensureNode(children, value, label) {
  let node = children.find((item) => item.value === value)
  if (!node) {
    node = { value, label, children: [] }
    children.push(node)
  }
  return node
}

const productTypeTreeMeta = computed(() => {
  const roots = []
  const idToPath = new Map()
  for (const m of (listingCategoryMappings.value || [])) {
    const idRaw = String(m?.mapping_id ?? '').trim()
    const typeName = String(m?.product_type ?? '').trim()
    if (!idRaw || !typeName) continue
    const id = Number(idRaw)
    if (!Number.isFinite(id)) continue
    const l1 = String(m?.category_level1 ?? '').trim() || '未分类'
    const l2 = String(m?.category_level2 ?? '').trim()
    const l3 = String(m?.category_level3 ?? '').trim()

    const l1Node = ensureNode(roots, `L1:${l1}`, l1)
    const l1Path = [`L1:${l1}`]
    if (!l2) {
      l1Node.children.push({ value: `PT:${id}`, label: typeName, children: [] })
      idToPath.set(id, [...l1Path, `PT:${id}`])
      continue
    }

    const l2Val = `L2:${l1}__${l2}`
    const l2Node = ensureNode(l1Node.children, l2Val, l2)
    const l2Path = [...l1Path, l2Val]
    if (!l3) {
      l2Node.children.push({ value: `PT:${id}`, label: typeName, children: [] })
      idToPath.set(id, [...l2Path, `PT:${id}`])
      continue
    }

    const l3Val = `L3:${l1}__${l2}__${l3}`
    const l3Node = ensureNode(l2Node.children, l3Val, l3)
    const l3Path = [...l2Path, l3Val]
    l3Node.children.push({ value: `PT:${id}`, label: typeName, children: [] })
    idToPath.set(id, [...l3Path, `PT:${id}`])
  }
  return { roots, idToPath }
})

const productTypeCascaderOptions = computed(() => productTypeTreeMeta.value.roots)

const DEFAULT_WH_LABEL = '默认仓库'
/** 与后端 WarehouseModel.normalize_warehouse_key 一致 */
function warehouseGroupKey(w) {
  const t = String(w?.warehouse ?? '').trim()
  return t || DEFAULT_WH_LABEL
}

/** 二级分组键：与仓库管理页一致，空 shelf_name 归为同一组 */
const EMPTY_SHELF_NAME_PART = '__shelf_name_empty__'

function shelfNamePartitionKey(w) {
  const raw = w?.shelf_name && String(w.shelf_name).trim() ? String(w.shelf_name).trim() : ''
  return raw || EMPTY_SHELF_NAME_PART
}

function shelfNamePartitionLabelFromKey(pk) {
  if (pk === EMPTY_SHELF_NAME_PART) return '（未设置货架名称）'
  return pk
}

/** 三级：仓库 → 货架名称(shelf_name) → 货架号(行 id) */
const warehouseTreeMeta = computed(() => {
  const list = Array.isArray(warehouses.value) ? warehouses.value : []
  const idToPath = new Map()
  const byWh = new Map()
  for (const w of list) {
    const wh = warehouseGroupKey(w)
    if (!byWh.has(wh)) byWh.set(wh, [])
    byWh.get(wh).push(w)
  }
  const roots = []
  const sortedWh = [...byWh.keys()].sort((a, b) => {
    if (a === DEFAULT_WH_LABEL) return -1
    if (b === DEFAULT_WH_LABEL) return 1
    return a.localeCompare(b, 'zh-CN')
  })
  for (const whName of sortedWh) {
    const rows = byWh.get(whName).slice()
    const byPartition = new Map()
    for (const w of rows) {
      const pk = shelfNamePartitionKey(w)
      if (!byPartition.has(pk)) byPartition.set(pk, [])
      byPartition.get(pk).push(w)
    }
    const l1Val = `WHG:${encodeURIComponent(whName)}`
    const midNodes = []
    const sortedPk = [...byPartition.keys()].sort((a, b) => {
      if (a === EMPTY_SHELF_NAME_PART) return 1
      if (b === EMPTY_SHELF_NAME_PART) return -1
      return a.localeCompare(b, 'zh-CN')
    })
    for (const pk of sortedPk) {
      const partRows = byPartition.get(pk).slice()
      partRows.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
      const l2Val = `WHSN:${encodeURIComponent(whName)}::${encodeURIComponent(pk)}`
      const labelMid = shelfNamePartitionLabelFromKey(pk)
      const leaves = partRows.map((w) => {
        const id = Number(w.id)
        const leafVal = `WHS:${w.id}`
        if (Number.isFinite(id)) idToPath.set(id, [l1Val, l2Val, leafVal])
        const code = String(w?.name ?? '').trim() || '（未设货架号）'
        return { value: leafVal, label: code, children: [] }
      })
      midNodes.push({ value: l2Val, label: labelMid, children: leaves })
    }
    roots.push({ value: l1Val, label: whName, children: midNodes })
  }
  return { roots, idToPath }
})

const warehouseCascaderOptions = computed(() => warehouseTreeMeta.value.roots)

function syncWarehouseCascaderPathByWarehouseId(wid) {
  const id = wid == null || wid === '' ? null : Number(wid)
  if (!Number.isFinite(id)) {
    warehouseCascaderPath.value = []
    return
  }
  const path = warehouseTreeMeta.value.idToPath.get(id)
  warehouseCascaderPath.value = path ? [...path] : []
}

function syncFilterWarehousePathByWarehouseId(wid) {
  const id = wid == null || wid === '' ? null : Number(wid)
  if (!Number.isFinite(id)) {
    filterWarehousePath.value = []
    return
  }
  const path = warehouseTreeMeta.value.idToPath.get(id)
  filterWarehousePath.value = path ? [...path] : []
}

function handleWarehouseCascaderChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('WHS:')) {
    form.value.warehouse_id = null
    formRef.value?.validateField('warehouse_id')
    return
  }
  const id = Number(String(picked).slice(4))
  form.value.warehouse_id = Number.isFinite(id) ? id : null
  formRef.value?.validateField('warehouse_id')
}

function handleFilterWarehouseChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('WHS:')) {
    filterWarehouse.value = null
    load()
    return
  }
  const id = Number(String(picked).slice(4))
  filterWarehouse.value = Number.isFinite(id) ? id : null
  load()
}

function syncCascaderPathByProductTypeId(typeId) {
  const normalized = typeId == null ? null : Number(typeId)
  if (!Number.isFinite(normalized)) {
    productTypeCascaderPath.value = []
    return
  }
  const path = productTypeTreeMeta.value.idToPath.get(normalized)
  productTypeCascaderPath.value = path ? [...path] : []
}

function handleProductTypeCascaderChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('PT:')) {
    form.value.product_type_id = null
    return
  }
  const id = Number(String(picked).slice(3))
  form.value.product_type_id = Number.isFinite(id) ? id : null
}

function handleFilterProductTypeChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('PT:')) {
    filterProductType.value = null
    load()
    return
  }
  const id = Number(String(picked).slice(3))
  filterProductType.value = Number.isFinite(id) ? id : null
  load()
}

async function confirmCreateCategory() {
  const name = newCategoryName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  const created = await categoryApi.create({ name })
  categories.value = await categoryApi.list()
  form.value.category_id = created?.id ?? form.value.category_id
  newCategoryName.value = ''
  categoryCreateMode.value = false
  ElMessage.success('分类创建成功')
}

/** 从指定 video 元素抓一帧，返回 Blob（JPEG） */
function captureFrame(videoElRef = videoRef) {
  const video = videoElRef.value
  if (!video || video.readyState < 2 || !video.videoWidth) return null
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d').drawImage(video, 0, 0)
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
}

async function load(options = {}) {
  const { resetPage = true } = options
  loading.value = true
  const params = {}
  if (keyword.value) params.keyword = keyword.value
  if (filterCat.value) params.category_id = filterCat.value
  if (filterWarehouse.value) params.warehouse_id = filterWarehouse.value
  if (filterProductType.value) params.product_type_id = filterProductType.value
  if (filterOwnerUserId.value) params.owner_user_id = filterOwnerUserId.value
  if (hideNoWarehouseSlot.value) params.in_stock_only = true
  list.value = await inventoryApi.list(params).finally(() => (loading.value = false))
  if (resetPage) {
    inventorySortProp.value = ''
    inventorySortOrder.value = ''
    currentPage.value = 1
    return
  }
  const totalPages = Math.max(1, Math.ceil(list.value.length / pageSize))
  if (currentPage.value > totalPages) currentPage.value = totalPages
  if (currentPage.value < 1) currentPage.value = 1
}

watch(hideNoWarehouseSlot, (v) => {
  try {
    localStorage.setItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY, v ? '1' : '0')
  } catch {
    /* ignore */
  }
  void load({ resetPage: false })
})

/** 与控制台相同：全库条目/总数量 + 接口返回的今日入出库（手机端不展示统计，一般不请求） */
async function loadInventoryStats() {
  if (isMobile.value) return
  const [inventoryItems, tx] = await Promise.all([
    inventoryApi.list(),
    transactionApi.list({ page_size: 10 }),
  ])
  const totalQuantity = inventoryItems.reduce((sum, p) => sum + (p.quantity || 0), 0)
  inventorySummary.value = {
    total_inventory: inventoryItems.length,
    total_quantity: totalQuantity,
    today_in: tx.today_in ?? '-',
    today_out: tx.today_out ?? '-',
  }
}

/** 与在售商品页一致：库存为 0（或以下）但仍有在售数量时标红并整体顶置 */
function isInventoryZeroStockOnSaleAlert(row) {
  if (!row || typeof row !== 'object') return false
  const qty = Number(row.quantity ?? 0)
  const onSale = Number(row.on_sale_quantity ?? 0)
  if (!Number.isFinite(onSale) || onSale <= 0) return false
  return Number.isFinite(qty) && qty <= 0
}

const sortedInventoryList = computed(() => {
  const arr = [...list.value]
  const prop = inventorySortProp.value
  const order = inventorySortOrder.value
  const mult = order === 'ascending' ? 1 : -1

  function alertOrder(a, b) {
    const aa = isInventoryZeroStockOnSaleAlert(a) ? 0 : 1
    const ba = isInventoryZeroStockOnSaleAlert(b) ? 0 : 1
    if (aa !== ba) return aa - ba
    return 0
  }

  function compareByColumn(a, b) {
    if (!prop || !order) {
      const ida = Number(a.id) || 0
      const idb = Number(b.id) || 0
      return idb - ida
    }
    if (prop === 'price') {
      const va = Number(a.price) || 0
      const vb = Number(b.price) || 0
      if (va < vb) return -1 * mult
      if (va > vb) return 1 * mult
      return 0
    }
    if (prop === 'cost_cny') {
      const va = Number(a.cost_cny)
      const vb = Number(b.cost_cny)
      const na = Number.isFinite(va) ? va : -1
      const nb = Number.isFinite(vb) ? vb : -1
      if (na < nb) return -1 * mult
      if (na > nb) return 1 * mult
      return 0
    }
    if (prop === 'quantity') {
      const va = Number(a.quantity) || 0
      const vb = Number(b.quantity) || 0
      if (va < vb) return -1 * mult
      if (va > vb) return 1 * mult
      return 0
    }
    if (prop === 'on_sale_quantity') {
      const va = Number(a.on_sale_quantity) || 0
      const vb = Number(b.on_sale_quantity) || 0
      if (va < vb) return -1 * mult
      if (va > vb) return 1 * mult
      return 0
    }
    if (prop === 'pending_outbound_qty') {
      const va = Number(a.pending_outbound_qty) || 0
      const vb = Number(b.pending_outbound_qty) || 0
      if (va < vb) return -1 * mult
      if (va > vb) return 1 * mult
      return 0
    }
    return 0
  }

  arr.sort((a, b) => {
    const ao = alertOrder(a, b)
    if (ao !== 0) return ao
    const co = compareByColumn(a, b)
    if (co !== 0) return co
    const ida = Number(a.id) || 0
    const idb = Number(b.id) || 0
    return idb - ida
  })
  return arr
})

function onInventorySortChange({ prop, order }) {
  inventorySortProp.value = order ? prop : ''
  inventorySortOrder.value = order || ''
  currentPage.value = 1
}

/** 库存数量：0 红色；1～3 黄色；大于 3 绿色 */
function quantityTagType(q) {
  const n = Number(q) || 0
  if (n === 0) return 'danger'
  if (n <= 3) return 'warning'
  return 'success'
}

/** 列表/展示：人民币成本，固定两位小数；空为「—」 */
function formatCostCny(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

/** 提交 API：人民币成本，最多两位小数；空为 null */
function normalizeCostCnyForPayload(v) {
  if (v == null || v === '') return null
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) return null
  return Math.round(n * 100) / 100
}

function sumRowsCostCny(rows) {
  if (!Array.isArray(rows) || !rows.length) return null
  let sum = 0
  let any = false
  for (const r of rows) {
    const n = Number(r?.cost_cny)
    if (Number.isFinite(n) && n > 0) {
      sum += n
      any = true
    }
  }
  if (!any) return null
  return Math.round(sum * 100) / 100
}

/**
 * 将本地 /imges/ 路径转为缩略图接口 URL（列表小图用）。
 * 非本地图片（外部 URL）原样返回。
 */
function thumbUrl(src, size = 200) {
  if (!src || !src.startsWith('/imges/')) return src
  return `/api/inventory/image-thumb?path=${encodeURIComponent(src)}&size=${size}`
}

/** 编辑弹窗内正/背面预览：已落盘路径走缩略图接口，data URL 原样 */
function inventoryFormImageSrc(side) {
  const raw = side === 'front' ? form.value.image_front : form.value.image_back
  if (!raw) return undefined
  if (typeof raw === 'string' && raw.startsWith('/imges/')) return thumbUrl(raw, 560)
  return raw
}

function abortNoBarcodeSideUpload(side) {
  const c = noBarcodeUploadAbortBySide[side]
  if (c) {
    c.abort()
    noBarcodeUploadAbortBySide[side] = null
  }
}

function abortAllNoBarcodeInventoryUploads() {
  abortNoBarcodeSideUpload('front')
  abortNoBarcodeSideUpload('back')
}

function resetNoBarcodeImageUploadState() {
  abortAllNoBarcodeInventoryUploads()
  noBarcodeImgUpload.value = {
    front: { uploading: false, percent: 0 },
    back: { uploading: false, percent: 0 },
  }
  nbCameraUploading.value = false
  nbCameraUploadPercent.value = 0
}

/** 无码新建：上传未结束时不可点保存 */
const inventorySaveBlockedByImageUpload = computed(() => {
  if (!isNoBarcodeNewInventory.value) return false
  if (noBarcodeImgUpload.value.front.uploading || noBarcodeImgUpload.value.back.uploading) return true
  if (nbCameraUploading.value) return true
  return false
})

function clearProductFormImage(side) {
  if (isNoBarcodeNewInventory.value) {
    abortNoBarcodeSideUpload(side)
    const slot = noBarcodeImgUpload.value[side]
    slot.uploading = false
    slot.percent = 0
  }
  if (side === 'front') form.value.image_front = null
  else form.value.image_back = null
}

function mercariItemIds(row) {
  const raw = String(row?.mercari_item_id || '').trim()
  if (!raw) return []
  const parts = raw
    .split(/[\n,，、\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const out = []
  const seen = new Set()
  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
  }
  return out
}

function getInventoryExpandSlot(inventoryId) {
  return inventoryExpandById.value[inventoryId] || null
}

function getInventoryExpandRows(row) {
  const slot = getInventoryExpandSlot(row?.id)
  if (!slot || !Array.isArray(slot.rows)) return []
  return slot.rows
}

function formatUnixTs(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const ms = n > 1e12 ? n : n * 1000
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return '-'
  const p2 = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}

function displayOnSaleStatus(status) {
  const key = String(status ?? '').trim()
  if (!key) return '-'
  return onSaleStatusMap[key]?.label || key
}

function onSaleStatusTagType(status) {
  const key = String(status ?? '').trim()
  return onSaleStatusMap[key]?.tag || 'info'
}

async function ensureInventoryExpandLoaded(row) {
  const id = row?.id
  if (!id) return
  if (!inventoryExpandById.value[id]) {
    inventoryExpandById.value[id] = { loading: false, loaded: false, rows: [] }
  }
  const slot = inventoryExpandById.value[id]
  if (slot.loading || slot.loaded) return
  const itemIds = mercariItemIds(row)
  if (!itemIds.length) {
    slot.rows = []
    slot.loaded = true
    return
  }
  slot.loading = true
  try {
    const res = await onSaleItemApi.listByItemIds({ item_ids: itemIds.join(',') })
    const rows = Array.isArray(res?.items) ? res.items : []
    const byId = new Map(rows.map((r) => [String(r.item_id || '').trim(), r]))
    slot.rows = itemIds.map((iid) => byId.get(String(iid).trim())).filter(Boolean)
    slot.loaded = true
  } catch {
    slot.rows = []
    slot.loaded = true
  } finally {
    slot.loading = false
  }
}

function onInventoryExpandChange(row, expandedRows) {
  const opened = Array.isArray(expandedRows) && expandedRows.some((r) => r?.id === row?.id)
  if (!opened) return
  ensureInventoryExpandLoaded(row)
}

const pagedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return sortedInventoryList.value.slice(start, start + pageSize)
})

function parseCombinedItemsPayload(raw) {
  if (!raw) return []
  if (Array.isArray(raw)) {
    return raw
      .map((x) => {
        if (!x || typeof x !== 'object') return null
        const inventory_id = Number(x.inventory_id)
        const quantity = Number(x.quantity)
        if (!Number.isFinite(inventory_id) || inventory_id <= 0) return null
        if (!Number.isFinite(quantity) || quantity <= 0) return null
        return { inventory_id, quantity }
      })
      .filter(Boolean)
  }
  if (typeof raw === 'string') {
    try {
      const p = JSON.parse(raw)
      return parseCombinedItemsPayload(p)
    } catch {
      return []
    }
  }
  return []
}

async function loadCombinedEditDetailForRow(row) {
  combinedEditDetailRows.value = []
  if (!row || Number(row.is_combined || 0) !== 1) return
  const parsed = parseCombinedItemsPayload(row.combined_items)
  if (!parsed.length) return
  combinedEditDetailLoading.value = true
  try {
    const rows = await Promise.all(
      parsed.map(async ({ inventory_id, quantity }) => {
        try {
          const p = await inventoryApi.get(inventory_id)
          const img = p?.image_front || p?.image || null
          return {
            inventory_id,
            per_combo_quantity: quantity,
            name: p?.name || '',
            image_front: img,
            current_quantity: p?.quantity ?? 0,
            loadError: null
          }
        } catch {
          return {
            inventory_id,
            per_combo_quantity: quantity,
            name: '',
            image_front: null,
            current_quantity: null,
            loadError: '无法加载该库存条目'
          }
        }
      })
    )
    combinedEditDetailRows.value = rows
  } finally {
    combinedEditDetailLoading.value = false
  }
}

function openDialog(row = null) {
  resetNoBarcodeImageUploadState()
  noBarcodeEntryMode.value = false
  categoryCreateMode.value = false
  newCategoryName.value = ''
  combinedEditDetailRows.value = []
  combinedEditDetailLoading.value = false
  form.value = row
    ? {
        id: row.id,
        barcode: row.barcode || '',
        name: row.name || null,
        sku: row.sku || null,
        category_id: row.category_id || null,
        product_type_id: row.product_type_id || null,
        owner_user_id: row.owner_user_id || null,
        warehouse_id: row.warehouse_id || null,
        price: Math.round(Number(row.price ?? 0)),
        cost_cny: (() => {
          const c = Number(row.cost_cny)
          return Number.isFinite(c) && c >= 0 ? Math.round(c * 100) / 100 : null
        })(),
        quantity: row.quantity ?? 0,
        mercari_item_id: row.mercari_item_id ?? '',
        on_sale_quantity: Number(row.on_sale_quantity ?? 0),
        description: row.description || null,
        listing_title: row.listing_title ?? '',
        listing_body: row.listing_body ?? '',
        image_front: row.image_front || row.image || null,
        image_back: row.image_back || null,
        is_combined: Number(row.is_combined || 0),
        combined_items: row.combined_items ?? null
      }
    : {
        id: null,
        barcode: '',
        name: null,
        sku: null,
        category_id: null,
        product_type_id: null,
        owner_user_id: null,
        warehouse_id: null,
        price: 0,
        cost_cny: null,
        quantity: 1,
        mercari_item_id: '',
        on_sale_quantity: 0,
        description: null,
        listing_title: '',
        listing_body: '',
        image_front: null,
        image_back: null,
        is_combined: 0,
        combined_items: null
      }
  syncQuantityEditFromForm()
  syncPriceEditFromForm()
  syncMercariIdListFromForm()
  syncCascaderPathByProductTypeId(form.value.product_type_id)
  syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
  dialogVisible.value = true
  if (row && Number(row.is_combined || 0) === 1) {
    loadCombinedEditDetailForRow(row)
  }
}

watch(dialogVisible, (visible) => {
  if (!visible) {
    resetNoBarcodeImageUploadState()
    noBarcodeEntryMode.value = false
    categoryCreateMode.value = false
    newCategoryName.value = ''
    combinedEditDetailRows.value = []
    combinedEditDetailLoading.value = false
  }
})

watch(
  warehouses,
  () => {
    if (dialogVisible.value) syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
    syncFilterWarehousePathByWarehouseId(filterWarehouse.value)
  },
  { deep: true }
)

function openNoBarcodeEntry() {
  openDialog()
  noBarcodeEntryMode.value = true
  const cached = readNoBarcodeFormSelectionsCache()
  if (cached) {
    form.value.category_id = cached.category_id
    form.value.product_type_id = cached.product_type_id
    form.value.owner_user_id = cached.owner_user_id
    form.value.warehouse_id = cached.warehouse_id
    syncCascaderPathByProductTypeId(form.value.product_type_id)
    syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
  }
  const selfUid = getCurrentAuthUserId()
  if (selfUid != null) {
    form.value.owner_user_id = selfUid
  }
  const uuid = (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `nb-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
  form.value.barcode = uuid
}

function buildListingSeedFromInventoryRows(rows) {
  if (!rows?.length) return null
  const first = rows[0]
  const names = rows.map((r) => String(r.name || '').trim()).filter(Boolean)
  let name = names.join('、')
  if (name.length > 200) name = `${name.slice(0, 197)}…`
  const listingTitles = rows.map((r) => String(r.listing_title || '').trim()).filter(Boolean)
  let listingTitle = listingTitles.join('、')
  if (!listingTitle) listingTitle = name
  if (listingTitle.length > 200) listingTitle = `${listingTitle.slice(0, 197)}…`
  const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
  const mappingId =
    sameType && first.product_type_id != null ? String(first.product_type_id) : null
  const descParts = rows
    .map((r) => {
      const b = String(r.listing_body ?? '').trim()
      if (b) return b
      return String(r.description ?? '').trim()
    })
    .filter(Boolean)
  const imageBack = rows.map((r) => r?.image_back).find((x) => x) || ''
  return {
    image: first.image_front || first.image || '',
    image_back: imageBack,
    name: name || String(first.name || '').trim() || '',
    listing_title: listingTitle || '',
    category_mapping_id: mappingId,
    description: descParts.join('\n---\n') || '',
    price: Math.round(Number(first.price ?? 0)),
    inventory_ids: rows.map((r) => r.id)
  }
}

/** 组合出品：仅用于预览多商品图；不预填名称与说明 */
function buildCombinedListingSeedFromInventoryRows(rows) {
  if (!rows?.length) return null
  const first = rows[0]
  const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
  const mappingId =
    sameType && first.product_type_id != null ? String(first.product_type_id) : null
  const combined_images = rows.map((r) => ({
    inventory_id: r.id,
    front: r.image_front || r.image || '',
    back: String(r.image_back || '').trim() || ''
  }))
  return {
    image: '',
    image_back: '',
    name: '',
    listing_title: String(first.listing_title || '').trim(),
    category_mapping_id: mappingId,
    description: '',
    /** 组合出品：取首条库存单价为初始值，保存时写回所选全部条目 */
    price: Math.round(Number(first.price ?? 0)),
    combined_images,
    inventory_ids: rows.map((r) => r.id)
  }
}

function toPositiveInt(value, fallback = 1) {
  const n = parseInt(String(value ?? '').trim(), 10)
  return Number.isFinite(n) && n > 0 ? n : fallback
}

function openCombinedProductDialog(rows) {
  if (!Array.isArray(rows) || !rows.length) return
  if (rows.some((r) => Number(r?.is_combined || 0) === 1)) {
    ElMessage.warning('组合商品不能再次作为组合来源')
    return
  }
  const first = rows[0]
  const sameCategory = rows.every((r) => r.category_id === first.category_id)
  const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
  const sameOwner = rows.every((r) => r.owner_user_id === first.owner_user_id)
  const sameWarehouse = rows.every((r) => r.warehouse_id === first.warehouse_id)
  combinedProductRows.value = rows.map((r) => ({ ...r, combine_quantity: 1 }))
  combinedProductForm.value = {
    name: `${rows.map((r) => String(r.name || '').trim()).filter(Boolean).join(' + ') || '组合商品'} 组合`,
    quantity: 1,
    price: rows.reduce((sum, r) => sum + Math.round(Number(r.price ?? 0)), 0),
    cost_cny: sumRowsCostCny(rows),
    description: '',
    category_id: sameCategory ? first.category_id : null,
    product_type_id: sameType ? first.product_type_id : null,
    owner_user_id: sameOwner ? first.owner_user_id : null,
    warehouse_id: sameWarehouse ? first.warehouse_id : null,
    /** 组合商品不继承来源库存的正/背面图，需在编辑中单独上传 */
    image_front: null,
    image_back: null
  }
  combinedProductDialogVisible.value = true
}

function normalizeCombinedProductItemQty(item) {
  item.combine_quantity = toPositiveInt(item.combine_quantity, 1)
}

async function submitCombinedProduct() {
  const comboQty = toPositiveInt(combinedProductForm.value.quantity, 0)
  if (comboQty <= 0) {
    ElMessage.warning('组合库存数必须大于 0')
    return
  }
  const name = String(combinedProductForm.value.name || '').trim()
  if (!name) {
    ElMessage.warning('请输入组合商品名称')
    return
  }
  if (combinedProductRows.value.some((r) => Number(r?.is_combined || 0) === 1)) {
    ElMessage.warning('组合商品不能再次作为组合来源')
    return
  }
  const components = combinedProductRows.value.map((r) => ({
    inventory_id: r.id,
    quantity: toPositiveInt(r.combine_quantity, 1)
  }))
  for (const comp of components) {
    const row = combinedProductRows.value.find((r) => r.id === comp.inventory_id)
    const need = comp.quantity * comboQty
    if (need > Number(row?.quantity || 0)) {
      ElMessage.warning(`管理番号 ${comp.inventory_id} 库存不足，需要 ${need}，当前 ${Number(row?.quantity || 0)}`)
      return
    }
  }
  const desc = String(combinedProductForm.value.description || '').trim()
  const payload = {
    name,
    quantity: comboQty,
    price: Math.max(0, Math.round(Number(combinedProductForm.value.price ?? 0))),
    cost_cny: normalizeCostCnyForPayload(combinedProductForm.value.cost_cny),
    description: desc || null,
    category_id: combinedProductForm.value.category_id || null,
    product_type_id: combinedProductForm.value.product_type_id || null,
    owner_user_id: combinedProductForm.value.owner_user_id || null,
    warehouse_id: combinedProductForm.value.warehouse_id || null,
    listing_title: name,
    listing_body: desc || null,
    image_front: null,
    image_back: null,
    components
  }
  combinedProductSubmitting.value = true
  try {
    const res = await inventoryApi.combine(payload)
    ElMessage.success(`组合商品已创建，管理番号：${res?.id ?? '-'}`)
    combinedProductDialogVisible.value = false
    await load({ resetPage: false })
    loadInventoryStats()
  } finally {
    combinedProductSubmitting.value = false
  }
}

/** 煤炉 WebDriver 自动化返回的 *_error 字段 → 中文项目名（用于「上架失败」提示） */
const WEB_DRIVE_LISTING_ERROR_LABELS = [
  ['switch_error', '页面开关'],
  ['images_error', '图片上传'],
  ['name_error', '商品名称'],
  ['category_error', '商品类型'],
  ['condition_error', '商品状态'],
  ['description_error', '商品说明'],
  ['shipping_payer_error', '快递费负担'],
  ['shipping_method_error', '配送方法'],
  ['shipping_from_error', '发货地址'],
  ['shipping_days_error', '发货天数'],
  ['sale_price_error', '销售方式与价格'],
  ['submit_error', '出品提交']
]

function collectWebDriveListingFailures(data) {
  if (!data || typeof data !== 'object') return []
  const out = []
  for (const [key, label] of WEB_DRIVE_LISTING_ERROR_LABELS) {
    const detail = data[key]
    if (detail != null && String(detail).trim()) {
      out.push({ key, label, detail: String(detail).trim() })
    }
  }
  return out
}

function formatWebDriveListingFailureMessage(failures, maxEach = 180) {
  return failures
    .map(({ label, detail }) => {
      const d = detail.length > maxEach ? `${detail.slice(0, maxEach)}…` : detail
      return `${label}：${d}`
    })
    .join('；')
}

/** 出品表单保存：写回所选库存的出品标题、listing_body、price（与编辑商品一致） */
async function onListingFormSaved(data) {
  const ids = (data.inventory_ids || []).map((id) => Number(id)).filter((x) => Number.isFinite(x))
  if (!ids.length) return
  const listing_title = data.listing_title != null ? String(data.listing_title).trim() : ''
  const listing_body = data.description != null ? String(data.description) : ''
  const price = Math.round(Number(data.price ?? 0))
  const safePrice = Number.isFinite(price) && price >= 0 ? price : 0

  // ── 1. 写回库存 出品标题、listing_body 与 price ───────────────────────── //
  try {
    for (const id of ids) {
      await inventoryApi.update(id, { listing_title, listing_body, price: safePrice })
    }
  } catch {
    // 错误提示由拦截器处理
    return
  }

  // ── 2. 派发出品自动化（开启浏览器，填写 Mercari 出品页） ─────────────── //
  const accountId = data.meilu_account_id
  if (!accountId) {
    ElMessage.success('出品标题、商品说明与单价已保存到库存（未选出品账号，跳过自动化）')
    await load({ resetPage: false })
    loadInventoryStats()
    return
  }

  // account_key 规则：meilu_{id}，与 webdrive profile 目录名一致
  const accountKey = `meilu_${accountId}`

  // 收集图片 URL：正面在前、背面在后；组合出品取所有 combined_images 的正面
  const imageUrls = []
  if (data.combined_images && Array.isArray(data.combined_images)) {
    for (const block of data.combined_images) {
      if (block.front) imageUrls.push(block.front)
      if (block.back) imageUrls.push(block.back)
    }
  } else {
    if (data.image) imageUrls.push(data.image)
    if (data.image_back) imageUrls.push(data.image_back)
  }

  const progressJobId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

  let lastConsoleStep = ''
  async function pollListingPostProgress() {
    try {
      const pr = await listingApi.getPostProgress(progressJobId)
      const d = pr?.data
      const zh = d?.label_zh
      if (zh) {
        listingPostProgressLabel.value = zh
        if (zh !== lastConsoleStep) {
          lastConsoleStep = zh
          console.log('[出品自动化]', zh)
        }
      }
    } catch {
      /* 轮询失败忽略 */
    }
  }

  listingPostOverlayTitle.value = '正在上架'
  listingPostOverlayFailed.value = false
  listingPostProgressLabel.value = '正在连接服务器…'
  listingPostOverlayVisible.value = true
  await pollListingPostProgress()
  listingPostProgressTimer = setInterval(pollListingPostProgress, 400)

  let listingPostHadStepErrors = false
  try {
    const res = await listingApi.postToMarket({
      account_key: accountKey,
      name: listing_title,
      description: listing_body,
      image_urls: imageUrls,
      category_mapping_id: data.category_mapping_id != null
        ? String(data.category_mapping_id)
        : null,
      status: data.status || '',
      shipping_payer: data.shipping_payer || 'seller',
      shipping_method: data.shipping_method || 'undecided',
      sale_type: data.sale_type || 'instant_buy',
      auction_duration: data.auction_duration || 'normal',
      price: safePrice,
      shipping_days: data.shipping_days || '2_3_days',
      shipping_from_area_id: data.shipping_from ? String(data.shipping_from) : '',
      use_mitm_proxy: true,
      progress_job_id: progressJobId
    })
    if (res?.success) {
      const d = res.data || {}
      const failures = collectWebDriveListingFailures(d)
      if (failures.length) {
        listingPostHadStepErrors = true
        const detailMsg = formatWebDriveListingFailureMessage(failures)
        listingPostOverlayTitle.value = '上架失败'
        listingPostOverlayFailed.value = true
        listingPostProgressLabel.value = detailMsg
        console.error('[出品自动化] 上架失败', failures)
        ElMessage.error(`上架失败：${detailMsg}`)
      } else {
        const parts = []
        if (d.images_uploaded) parts.push(`已上传 ${d.images_uploaded} 张图片`)
        if (d.name_filled) parts.push('出品标题已填写')
        if (d.description_filled) parts.push('商品说明已填写')
        if (d.category_selected) parts.push('商品类型已选择')
        if (d.sell_wizard_back_clicked) parts.push('已从煤炉出品向导返回表单')
        if (d.condition_set) parts.push('商品状态已选择')
        if (d.shipping_payer_set) parts.push('快递费负担已设置')
        if (d.shipping_method_set) parts.push('配送方法已设置')
        if (d.sale_type_set && d.price_filled) parts.push('销售方式与价格已填写')
        if (d.shipping_days_set) parts.push('发货天数已设置')
        if (d.shipping_from_set) parts.push('发货地址已设置')
        if (d.submitted === true) {
          ElMessage.success('出品成功！' + (d.submit_message ? `（${d.submit_message}）` : ''))
        } else if (d.submitted === false && d.submit_message) {
          ElMessage.warning(`出品提示异常：${d.submit_message}`)
        } else {
          ElMessage.success(
            parts.length ? `出品页填写完成：${parts.join('、')}` : '浏览器已打开出品页'
          )
        }
      }
    }
  } catch {
    // axios 拦截器已弹窗，此处仅记录
  } finally {
    if (listingPostProgressTimer != null) {
      clearInterval(listingPostProgressTimer)
      listingPostProgressTimer = null
    }
    if (listingPostHadStepErrors) {
      await new Promise((r) => setTimeout(r, 1200))
    }
    listingPostOverlayVisible.value = false
    listingPostOverlayTitle.value = '正在上架'
    listingPostOverlayFailed.value = false
    listingPostProgressLabel.value = ''
  }

  if (listingPostHadStepErrors) {
    ElMessage.info(
      '出品标题、商品说明与单价已写入本地库存。煤炉自动化有失败步骤，请根据上方红色提示在浏览器中补全或重试。'
    )
  } else {
    ElMessage.success('出品标题、商品说明与单价已保存到库存')
  }
  await load({ resetPage: false })
  loadInventoryStats()
}

/** 组合商品可选：库存大于 0，且不能是已有组合 SKU（禁止二次组合） */
function isListingPickSelectable(row) {
  if (Number(row?.is_combined || 0) === 1) return false
  return Number(row?.quantity ?? 0) > 0
}

/** 进入「组合商品」：在列表中单选或多选库存后再填表单（单条时可调「每套数量」） */
async function enterListingPickMode() {
  listingPickMode.value = true
  listingPickIds.value = new Set()
  closeAllInlineEditors()
  await load({ resetPage: false })
}

/** 「出品」：当前行直接打开出品表单（单条库存） */
function openListingFormForRow(row) {
  if (!row || row.id == null) return
  if (Number(row?.quantity ?? 0) <= 0) {
    ElMessage.warning('库存为 0 的商品无法出品')
    return
  }
  listingSeedData.value = buildListingSeedFromInventoryRows([row])
  listingDialogVisible.value = true
}

async function exitListingPickMode() {
  listingPickMode.value = false
  listingPickIds.value = new Set()
  await load({ resetPage: false })
}

function toggleListingPickRow(row) {
  if (!row || row.id == null) return
  const next = new Set(listingPickIds.value)
  if (next.has(row.id)) {
    next.delete(row.id)
    listingPickIds.value = next
    return
  }
  if (Number(row?.is_combined || 0) === 1) {
    ElMessage.warning('组合商品不能再次作为组合来源')
    return
  }
  if (Number(row?.quantity ?? 0) <= 0) {
    ElMessage.warning('库存为 0 的商品不能选中')
    return
  }
  next.add(row.id)
  listingPickIds.value = next
}

function rowClassName({ row }) {
  const classes = []
  if (isInventoryZeroStockOnSaleAlert(row)) {
    classes.push('on-sale-stock-alert-row')
  }
  if (listingPickMode.value && listingPickIds.value.has(row?.id)) {
    classes.push('listing-pick-row-selected')
  }
  if (listingPickMode.value && !isListingPickSelectable(row)) {
    classes.push('listing-pick-row-disabled')
  }
  return classes.filter(Boolean).join(' ')
}

function onTableRowClick(row) {
  if (!listingPickMode.value) return
  toggleListingPickRow(row)
}

function closeAllInlineEditors() {
  editingCategoryRowId.value = null
  editingProductTypeRowId.value = null
  editingOwnerRowId.value = null
  editingCell.value = ''
  editingValue.value = ''
}

async function confirmListingPick() {
  if (!listingPickIds.value.size) {
    ElMessage.warning('请至少选择一条商品')
    return
  }
  const idSet = listingPickIds.value
  const rows = sortedInventoryList.value.filter(
    (r) => idSet.has(r.id) && isListingPickSelectable(r)
  )
  if (!rows.length) {
    ElMessage.warning('所选商品无法用于组合（库存为 0 或已为组合商品）')
    return
  }
  await exitListingPickMode()
  openCombinedProductDialog(rows)
}

function triggerFileInputOnly(side) {
  if (side === 'front') fileInputFront.value?.click()
  else fileInputBack.value?.click()
}

function triggerProductImageFilePick(side) {
  if (side === 'front') fileInputFrontPick.value?.click()
  else fileInputBackPick.value?.click()
}

function stopProductImgCameraStream() {
  if (productImgStream) {
    productImgStream.getTracks().forEach((t) => t.stop())
    productImgStream = null
  }
  const el = productImgVideoRef.value
  if (el) el.srcObject = null
}

function onProductImgCameraClosed() {
  productImgPreviewUrl.value = null
  productImgCameraSelectId.value = ''
  stopProductImgCameraStream()
}

async function onProductImgCameraDeviceChanged(deviceId) {
  if (!deviceId || productImgCapturing.value || productImgPreviewUrl.value) return
  const v = productImgVideoRef.value
  if (!v) return
  stopProductImgCameraStream()
  try {
    productImgStream = await getInventoryCameraStream(deviceId)
    v.srcObject = productImgStream
    await new Promise((resolve) => {
      v.onloadedmetadata = resolve
    })
    await refreshInventoryCameraDeviceList(productImgStream)
    syncInventoryCameraSelectFromStream(productImgStream)
    productImgCameraSelectId.value = inventoryCameraSelectId.value
    const okDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
    if (okDev) writeSavedInventoryCameraDeviceId(okDev)
  } catch {
    ElMessage.error('无法切换到所选摄像头，将尝试默认摄像头')
    try {
      productImgStream = await getInventoryCameraStream(null)
      v.srcObject = productImgStream
      await new Promise((resolve) => {
        v.onloadedmetadata = resolve
      })
      await refreshInventoryCameraDeviceList(productImgStream)
      syncInventoryCameraSelectFromStream(productImgStream)
      productImgCameraSelectId.value = inventoryCameraSelectId.value
      const fbDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
      if (fbDev) writeSavedInventoryCameraDeviceId(fbDev)
    } catch {
      ElMessage.error('无法打开摄像头，将改为从本机选择图片')
      productImgCameraVisible.value = false
      stopProductImgCameraStream()
      triggerFileInputOnly(productImgCameraSide.value)
    }
  }
}

/**
 * 正/背面图：PC/Android（非 iOS）且支持 getUserMedia 时打开摄像头弹窗抓拍；
 * iOS 或无 API 时用隐藏 file（iOS 带 capture）。
 */
async function openProductImageSource(side) {
  const canStream = typeof navigator.mediaDevices?.getUserMedia === 'function'
  if (canStream && !isIOS.value) {
    productImgCameraSide.value = side
    productImgPreviewUrl.value = null
    productImgCameraVisible.value = true
    await nextTick()
    stopProductImgCameraStream()
    try {
      const saved = readSavedInventoryCameraDeviceId()
      productImgStream = await getInventoryCameraStream(saved)
      const v = productImgVideoRef.value
      if (!v) return
      v.srcObject = productImgStream
      await new Promise((resolve) => {
        v.onloadedmetadata = () => resolve()
      })
      await refreshInventoryCameraDeviceList(productImgStream)
      syncInventoryCameraSelectFromStream(productImgStream)
      productImgCameraSelectId.value = inventoryCameraSelectId.value
      const curDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
      if (curDev) writeSavedInventoryCameraDeviceId(curDev)
    } catch {
      ElMessage.error('无法打开摄像头，将改为从本机选择图片')
      productImgCameraVisible.value = false
      stopProductImgCameraStream()
      triggerFileInputOnly(side)
    }
    return
  }
  triggerFileInputOnly(side)
}

/** 从当前预览流生成静态预览，不写入表单 */
async function takeProductImgDraft() {
  productImgCapturing.value = true
  try {
    const blob = await captureFrame(productImgVideoRef)
    if (!blob) {
      ElMessage.warning('请等待摄像头画面就绪后再拍')
      return
    }
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = () => reject(new Error('read'))
      reader.readAsDataURL(blob)
    })
    productImgPreviewUrl.value = dataUrl
  } catch {
    ElMessage.warning('读取照片失败，请重试')
  } finally {
    productImgCapturing.value = false
  }
}

function retakeProductImg() {
  productImgPreviewUrl.value = null
}

/** 用户确认后写入正/背面并关闭 */
async function applyProductImgConfirm() {
  const url = productImgPreviewUrl.value
  if (!url) return
  productImgCapturing.value = true
  nbCameraUploadPercent.value = 0
  const side = productImgCameraSide.value
  try {
    if (isNoBarcodeNewInventory.value) {
      nbCameraUploading.value = true
      let blob
      try {
        const resFetch = await fetch(url)
        blob = await resFetch.blob()
      } catch {
        ElMessage.warning('读取照片失败，请重试')
        return
      }
      const mime = blob.type && blob.type.startsWith('image/') ? blob.type : 'image/jpeg'
      const file = new File([blob], 'capture.jpg', { type: mime })
      if (file.size > MAX_UPLOAD_IMAGE_BYTES) {
        ElMessage.warning('图片不能超过25MB')
        return
      }
      const res = await inventoryApi.uploadImage(file, (pe) => {
        if (!pe.total) return
        nbCameraUploadPercent.value = Math.min(100, Math.round((pe.loaded / pe.total) * 100))
      })
      const path = res?.path || ''
      if (!path) {
        ElMessage.error('上传失败：未返回路径')
        return
      }
      if (side === 'front') {
        form.value.image_front = path
        formRef.value?.validateField('image_front')
      } else {
        form.value.image_back = path
      }
      productImgCameraVisible.value = false
    } else {
      if (side === 'front') {
        form.value.image_front = url
        formRef.value?.validateField('image_front')
      } else {
        form.value.image_back = url
      }
      productImgCameraVisible.value = false
    }
  } catch (err) {
    if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return
  } finally {
    productImgCapturing.value = false
    nbCameraUploading.value = false
    nbCameraUploadPercent.value = 0
  }
}

async function handleImageUpload(e, side) {
  const file = e.target.files?.[0]
  if (e.target) e.target.value = ''
  if (!file) return
  if (file.size > MAX_UPLOAD_IMAGE_BYTES) {
    ElMessage.warning('图片不能超过25MB')
    return
  }

  if (isNoBarcodeNewInventory.value) {
    abortNoBarcodeSideUpload(side)
    const ac = new AbortController()
    noBarcodeUploadAbortBySide[side] = ac
    const slot = noBarcodeImgUpload.value[side]
    slot.uploading = true
    slot.percent = 0
    try {
      const res = await inventoryApi.uploadImage(
        file,
        (pe) => {
          if (!pe.total) return
          slot.percent = Math.min(100, Math.round((pe.loaded / pe.total) * 100))
        },
        ac.signal
      )
      const path = res?.path || ''
      if (!path) {
        ElMessage.error('上传失败：未返回路径')
        return
      }
      if (side === 'front') {
        form.value.image_front = path
        formRef.value?.validateField('image_front')
      } else {
        form.value.image_back = path
      }
    } catch (err) {
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return
    } finally {
      slot.uploading = false
      slot.percent = 0
      if (noBarcodeUploadAbortBySide[side] === ac) noBarcodeUploadAbortBySide[side] = null
    }
    return
  }

  const reader = new FileReader()
  reader.onload = (ev) => {
    if (side === 'front') {
      form.value.image_front = ev.target.result
      formRef.value?.validateField('image_front')
    } else {
      form.value.image_back = ev.target.result
    }
  }
  reader.readAsDataURL(file)
}

async function submit() {
  applyQuantityEditToForm()
  applyPriceEditToForm()
  applyMercariIdListToForm()
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = { ...form.value }
    payload.price = Math.round(Number(payload.price ?? 0))
    payload.cost_cny = normalizeCostCnyForPayload(payload.cost_cny)
    if (payload.mercari_item_id !== undefined && payload.mercari_item_id !== null) {
      payload.mercari_item_id = String(payload.mercari_item_id).trim() || null
    }
    if (payload.on_sale_quantity != null) {
      payload.on_sale_quantity = Math.max(0, Math.round(Number(payload.on_sale_quantity)))
    }
    delete payload.is_combined
    delete payload.combined_items
    delete payload.sku
    if (payload.id) {
      await inventoryApi.update(payload.id, payload)
    } else {
      await inventoryApi.create(payload)
      if (noBarcodeEntryMode.value) {
        writeNoBarcodeFormSelectionsCache(payload)
      }
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await load({ resetPage: false })
    loadInventoryStats()
  } finally {
    submitting.value = false
  }
}

async function remove(id) {
  await inventoryApi.remove(id)
  ElMessage.success('删除成功')
  await load({ resetPage: false })
  loadInventoryStats()
}

async function openScanDialog() {
  stopScan()
  scanning.value = false

  // HTTP 非安全上下文下 Chromium 不暴露 mediaDevices → 只能选图
  const canStream = typeof navigator.mediaDevices?.getUserMedia === 'function'
  if (!canStream) {
    if (!window.isSecureContext) {
      ElMessage.warning('HTTP 非 localhost 无法使用摄像头，已改为选图。请用 https:// 打开（自签名证书点继续访问）或 http://localhost:9600。')
    }
    cameraInputRef.value.value = ''
    cameraInputRef.value.click()
    return
  }

  scanVisible.value = true
  await nextTick()

  try {
    const savedCam = readSavedInventoryCameraDeviceId()
    mediaStream = await getInventoryCameraStream(savedCam)
    videoRef.value.srcObject = mediaStream

    // 等视频就绪后再开始抓帧
    await new Promise((resolve) => {
      videoRef.value.onloadedmetadata = resolve
    })

    scanTimer = setInterval(async () => {
      if (!scanVisible.value || scanning.value) return
      const blob = await captureFrame()
      if (!blob) return
      scanning.value = true
      try {
        const res = await scanApi.scanBarcode(blob)
        if (res?.found && res.barcode) {
          form.value.barcode = res.barcode
          ElMessage.success(`扫码成功：${res.barcode}`)
          scanVisible.value = false
        }
      } catch {
        // 识别失败时静默，继续下一帧
      } finally {
        scanning.value = false
      }
    }, SCAN_INTERVAL_MS)
  } catch {
    ElMessage.error('无法打开摄像头，请检查浏览器摄像头权限后重试。')
    scanVisible.value = false
  }
}

function stopScan() {
  if (scanTimer) {
    clearInterval(scanTimer)
    scanTimer = null
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop())
    mediaStream = null
  }
  scanning.value = false
}

/** iOS Safari / 非安全上下文：拍照后将图片文件送后端识别 */
async function handleCameraCapture(e) {
  const file = e.target.files?.[0]
  if (!file) return
  e.target.value = ''

  try {
    const res = await scanApi.scanBarcode(file)
    if (res?.found && res.barcode) {
      form.value.barcode = res.barcode
      ElMessage.success(`扫码成功：${res.barcode}`)
    } else {
      ElMessage.warning('未能识别条形码，请确保照片清晰并对准条形码')
    }
  } catch {
    ElMessage.warning('识别请求失败，请检查网络连接后重试')
  }
}

// ============ 连续扫码函数 ============

async function openContScan() {
  stopContScan()
  contQuantity.value = 1
  contBarcode.value = ''
  contProduct.value = null
  contScanNeedsHttpsHint.value = false

  const canUseStream = typeof navigator.mediaDevices?.getUserMedia === 'function'

  // iOS：仍直接唤起相册/相机，避免多余一步
  if (isIOS.value) {
    contScanMode.value = 'fallback'
    contState.value = 'ios-fallback'
    contScanVisible.value = false
    triggerContCapture()
    return
  }

  // Windows / Android 桌面浏览器：HTTP 下无 mediaDevices，先显示说明弹窗，避免直接弹出「打开文件」
  if (!canUseStream) {
    contScanMode.value = 'fallback'
    contState.value = 'ios-fallback'
    contScanNeedsHttpsHint.value = !window.isSecureContext
    contScanVisible.value = true
    return
  }

  contScanMode.value = 'stream'
  contState.value = 'scanning'
  contScanVisible.value = true
  await nextTick()

  try {
    const savedCam = readSavedInventoryCameraDeviceId()
    contStream = await getInventoryCameraStream(savedCam)
    contVideoRef.value.srcObject = contStream
    await new Promise((resolve) => { contVideoRef.value.onloadedmetadata = resolve })
    await refreshInventoryCameraDeviceList(contStream)
    syncInventoryCameraSelectFromStream(contStream)
    const curDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
    if (curDev) writeSavedInventoryCameraDeviceId(curDev)
    startContTimer()
  } catch {
    ElMessage.error('无法打开摄像头，请检查权限后重试')
    contScanVisible.value = false
  }
}

function startContTimer() {
  contTimer = setInterval(async () => {
    if (contState.value !== 'scanning' || contScanning.value) return
    const blob = await captureFrame(contVideoRef)
    if (!blob) return
    contScanning.value = true
    try {
      const res = await scanApi.scanBarcode(blob)
      if (res?.found && res.barcode) {
        await handleContBarcode(res.barcode)
      }
    } catch { /* 静默失败，继续扫 */ } finally {
      contScanning.value = false
    }
  }, SCAN_INTERVAL_MS)
}

async function handleContBarcode(barcode) {
  // 停止扫码循环，等待用户操作
  clearInterval(contTimer)
  contTimer = null
  contBarcode.value = barcode

  try {
    const res = await inventoryApi.findByBarcode(barcode)
    if (res?.found) {
      contProduct.value = res.product
      contQuantity.value = 1
      contState.value = 'found'
    } else {
      contState.value = 'notfound'
    }
  } catch {
    ElMessage.error('查询商品失败，请检查网络连接')
    contState.value = 'notfound'
  }
}

function resumeContScan() {
  contBarcode.value = ''
  contProduct.value = null
  if (contScanMode.value === 'fallback') {
    contState.value = 'ios-fallback'
    triggerContCapture()
    return
  }
  contState.value = 'scanning'
  if (contStream) {
    startContTimer()
  }
}

async function confirmContAction() {
  if (!contProduct.value?.warehouse_id) {
    ElMessage.warning('该商品未设置所属货架，请先编辑商品后再操作')
    return
  }
  contConfirming.value = true
  try {
    const quantity = Math.max(1, Math.round(Number(contQuantity.value) || 1))
    const res = await inventoryApi.stockIn(contProduct.value.id, {
      warehouse_id: contProduct.value.warehouse_id,
      quantity,
      remark: '连续扫码入库'
    })
    ElMessage.success(`入库成功，当前库存：${res.new_quantity} 件`)
    load()
    loadInventoryStats()
    contScanVisible.value = false
  } catch {
    // 错误由 axios 拦截器统一提示
  } finally {
    contConfirming.value = false
  }
}

function openAddFromScan() {
  const barcode = contBarcode.value
  contScanVisible.value = false
  openDialog()
  // nextTick 等对话框挂载后再填写 barcode
  nextTick(() => { form.value.barcode = barcode })
}

function stopContScan() {
  clearInterval(contTimer)
  contTimer = null
  contScanNeedsHttpsHint.value = false
  if (contStream) {
    contStream.getTracks().forEach((t) => t.stop())
    contStream = null
  }
  contScanning.value = false
}

function triggerContCapture() {
  contCaptureUseA = !contCaptureUseA
  const el = contCaptureUseA ? contCameraRefA.value : contCameraRefB.value
  if (!el) return
  el.value = ''
  el.click()
}

async function handleContCapture(e) {
  const file = e.target.files?.[0]
  if (!file) return
  e.target.value = ''
  contScanning.value = true
  try {
    const res = await scanApi.scanBarcode(file)
    if (res?.found && res.barcode) {
      if (!contScanVisible.value) {
        contScanVisible.value = true
        await nextTick()
      }
      await handleContBarcode(res.barcode)
    } else {
      ElMessage.warning('未识别到条形码，请重拍')
    }
  } catch {
    ElMessage.warning('识别失败，请重试')
  } finally {
    contScanning.value = false
  }
}

// ============ 条形码寻找函数 ============

watch(isMobile, (mobile) => {
  if (!mobile) loadInventoryStats()
})

// ============ 生命周期 ============

onBeforeUnmount(stopScan)
onBeforeUnmount(stopContScan)

async function refreshListingDefaults() {
  try {
    const d = await configApi.getListingDefaults()
    listingDefaultsFromServer.value = {
      shipping_from_area_id: d?.shipping_from_area_id ?? null,
      shipping_method: d?.shipping_method ?? null,
      shipping_payer: d?.shipping_payer ?? null,
      shipping_days: d?.shipping_days ?? null,
      meilu_account_id: d?.meilu_account_id ?? null
    }
  } catch {
    /* 拦截器已提示；保持当前占位 */
  }
}

onMounted(async () => {
  updateViewportState()
  window.addEventListener('resize', updateViewportState)
  const [cats, whs, users, mappings] = await Promise.all([
    categoryApi.list(),
    warehouseApi.list(),
    authApi.listUsers(),
    productTypeCategoryMappingApi.list()
  ])
  await refreshListingDefaults()
  categories.value = cats
  warehouses.value = whs
  productTypes.value = buildProductTypeOptionsFromMappings(mappings)
  ownerUsers.value = users
  listingCategoryMappings.value = mappings
  syncCascaderPathByProductTypeId(form.value.product_type_id)
  await Promise.all([load(), loadInventoryStats()])
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportState)
  stopScan()
  stopContScan()
  onProductImgCameraClosed()
  if (listingPostProgressTimer != null) {
    clearInterval(listingPostProgressTimer)
    listingPostProgressTimer = null
  }
})
</script>

<style scoped>
.section-card { margin-bottom: 16px; border-radius: 8px; }
.inventory-stats-wrap { margin-bottom: 16px; }
.inventory-stat-row { margin-bottom: 0; }
.stat-row .el-col { margin-bottom: 16px; }
.inv-stat-card {
  background: #131c2f;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  border-top: 3px solid;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  border: 1px solid #2a3446;
}
.inv-stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.inv-stat-value { font-size: 22px; font-weight: 700; color: #ecf2ff; }
.inv-stat-label { font-size: 12px; color: #9ba8bf; margin-top: 2px; }
.search-card { margin-bottom: 16px; border-radius: 8px; }
.search-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.search-actions--ios {
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}
.search-actions-ios-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  width: 100%;
  justify-content: stretch;
}
.search-actions-ios-row :deep(.el-button) {
  flex: 1;
  min-width: 0;
  margin: 0;
}
.search-row {
  justify-content: space-between;
}
.search-left-group {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
}
.search-left-row1 {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 20px;
  width: 100%;
}
.search-filters-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  flex-shrink: 0;
}
.search-input-control,
.search-select-control {
  width: 180px;
  max-width: 180px;
}
.search-filters-row .search-select-control {
  width: 180px;
  max-width: 180px;
}
.search-filters-row .search-filter-checkbox {
  flex: 0 0 auto;
  margin-right: 0;
  white-space: nowrap;
}
.search-filters-row .search-filter-checkbox :deep(.el-checkbox__label) {
  padding-left: 6px;
}
.product-field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  flex-wrap: wrap;
}
.product-field-inline__main {
  flex: 1;
  min-width: 0;
}
.product-field-inline :deep(.el-select),
.product-field-inline :deep(.el-input) {
  width: 100%;
}
.product-qty-input {
  width: 30px;
}
.product-qty-input :deep(.el-input__wrapper) {
  padding-left: 1px;
  padding-right: 1px;
  justify-content: center;
}
.product-qty-input :deep(input) {
  text-align: center;
}
/* 编辑商品弹窗：组合商品左右分栏，右侧组成明细 */
.product-edit-dialog-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.product-edit-dialog-layout--combined {
  flex-direction: row;
  align-items: flex-start;
  gap: 20px;
}
.product-edit-dialog-layout__form {
  flex: 1 1 auto;
  min-width: 0;
}
.product-edit-dialog-layout__aside {
  flex: 0 0 312px;
  width: 312px;
  max-width: 100%;
  padding: 12px 14px 14px;
  border-radius: 8px;
  border: 1px solid #28354a;
  background: #18233a;
  box-sizing: border-box;
  align-self: stretch;
}
.combined-edit-aside-title {
  font-size: 15px;
  font-weight: 600;
  color: #e6edf7;
  margin-bottom: 6px;
}
.combined-edit-aside-sub {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  margin: 0 0 12px;
}
.combined-edit-aside-sub strong {
  color: #c8d8f0;
}
.combined-edit-aside-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: min(52vh, 520px);
  overflow-y: auto;
}
.combined-edit-aside-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #28354a;
  background: #131c2f;
}
.combined-edit-aside-item__thumb {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
}
.combined-edit-aside-item__img {
  width: 48px;
  height: 48px;
  border-radius: 6px;
  border: 1px solid #28354a;
  overflow: hidden;
  display: block;
}
.combined-edit-aside-item__img :deep(.el-image__inner) {
  object-fit: cover;
}
.combined-edit-aside-item__img-fallback,
.combined-edit-aside-item__img-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 6px;
  border: 1px dashed #3d4d66;
  background: #0b1220;
  font-size: 11px;
  color: #64748b;
  box-sizing: border-box;
}
.combined-edit-aside-item__body {
  flex: 1 1 auto;
  min-width: 0;
}
.combined-edit-aside-item__title {
  font-size: 13px;
  font-weight: 600;
  color: #e6edf7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.combined-edit-aside-item__meta {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
}
.combined-edit-aside-item__meta strong {
  color: #c8d8f0;
}
.combined-edit-aside-item__err {
  color: #f56c6c;
}
.combined-edit-aside-empty {
  font-size: 12px;
  color: #64748b;
  padding: 12px 4px;
  text-align: center;
}
@media (max-width: 768px) {
  .product-edit-dialog-layout--combined {
    flex-direction: column;
  }
  .product-edit-dialog-layout__aside {
    flex: none;
    width: 100%;
  }
  .combined-edit-aside-list {
    max-height: none;
  }
}

.table-card { border-radius: 8px; }
/* 与订单页 #/orders 列表缩略图一致 */
.order-thumb {
  width: 48px;
  height: 48px;
  border-radius: 4px;
  display: block;
}
.thumb-fallback {
  color: #909399;
  font-size: 12px;
}
.table-scroll { width: 100%; overflow-x: auto; }
.table-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.editable-cell {
  min-height: 24px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s;
}
.editable-cell:hover {
  background: rgba(64, 158, 255, 0.12);
}
.inline-input { width: 100%; }
.cell-center { text-align: center; }
.cell-right { text-align: right; }
.cell-muted { color: #909399; font-size: 13px; }
.multi-line-cell {
  display: flex;
  flex-direction: column;
}
.multi-line-cell > div {
  min-height: 30px;
  line-height: 30px;
  box-sizing: border-box;
}
.multi-line-cell--compact > div {
  min-height: 22px;
  line-height: 22px;
}
/* ---- 库存展开：二级表格 ---- */
.inventory-expand-wrap {
  padding: 8px 12px 12px 48px;
  min-height: 48px;
}
.inventory-expand-inner-table {
  width: 100%;
}

/* ---- 编辑弹窗：煤炉商品ID 列表编辑器 ---- */
.mercari-id-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.mercari-id-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mercari-id-input {
  flex: 1;
}
.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
}

.image-upload-area {
  width: 120px;
  height: 120px;
  border: 2px dashed #3b4961;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: border-color 0.2s;
}
.image-upload-area.large {
  width: 100%;
  height: 180px;
}
.image-upload-area:hover { border-color: #409EFF; }
.preview-img { width: 100%; height: 100%; object-fit: cover; }
.upload-placeholder { text-align: center; }
.upload-tip { font-size: 12px; color: #8e9bb3; margin-top: 8px; }
.img-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.img-label-row .img-label { margin-bottom: 0; flex: 1; min-width: 0; }
.img-label { font-size: 13px; color: #8e9bb3; margin-bottom: 8px; }
.img-actions { display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
.nb-inventory-upload-progress { margin-top: 10px; width: 100%; }
.nb-inventory-upload-progress--camera { margin-top: 14px; }
.nb-inventory-upload-hint { font-size: 12px; color: #909399; margin-top: 6px; text-align: center; }
.scanning-hint { color: #409EFF; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

/* ---- OCR ---- */
.ocr-hint { font-size: 13px; color: #8e9bb3; text-align: center; margin-bottom: 10px; }
.ocr-img-tabs { display: flex; gap: 8px; margin-bottom: 10px; }
.ocr-canvas-wrap { width: 100%; background: #000; border-radius: 6px; overflow: hidden; }
.ocr-canvas { display: block; width: 100%; cursor: crosshair; touch-action: none; user-select: none; }
.ocr-loading { text-align: center; padding: 10px 0; }

/* ---- 连续扫码结果区 ---- */
.header-actions { display: flex; gap: 10px; }
.barcode-tag {
  display: inline-flex; align-items: center; gap: 8px;
  background: #1e2d42; border: 1px solid #3b4961; border-radius: 20px;
  padding: 6px 16px; font-size: 15px; font-weight: 600;
  color: #7eb8f7; margin-bottom: 16px;
}
.product-images-row {
  display: flex; gap: 12px; justify-content: center; margin-bottom: 14px;
}
.result-img-wrap {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.img-side-label { font-size: 11px; color: #8e9bb3; }
.result-img { width: 130px; height: 130px; object-fit: cover; border-radius: 8px; border: 1px solid #2d3f56; }
.no-image-placeholder {
  display: flex; flex-direction: column; align-items: center;
  color: #4a5a72; padding: 20px;
}
.product-meta {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 4px;
}
.product-meta-name { font-size: 15px; font-weight: 600; color: #c8d8f0; }
.cont-quantity-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.cont-quantity-label { color: #8e9bb3; font-size: 13px; }
.notfound-box {
  display: flex; flex-direction: column; align-items: center;
  padding: 24px 0; color: #e6a23c;
}
.notfound-box p { margin-top: 10px; font-size: 15px; }
.cont-result { display: flex; flex-direction: column; align-items: center; padding: 8px 0 4px; }
.cont-actions { display: flex; gap: 14px; margin-top: 20px; }
.ios-fallback-box { display: flex; flex-direction: column; align-items: center; padding: 32px 0; }
.cont-https-hint {
  color: #e6a23c;
  font-size: 13px;
  line-height: 1.55;
  text-align: left;
  max-width: 100%;
  margin: 0 0 12px;
  padding: 10px 12px;
  background: rgba(230, 162, 60, 0.12);
  border-radius: 8px;
  border: 1px solid rgba(230, 162, 60, 0.35);
}
.cont-https-hint code { font-size: 12px; }

.scan-box { display: flex; flex-direction: column; gap: 10px; }
.camera-device-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.camera-device-label {
  flex-shrink: 0;
  color: #9aa7be;
  font-size: 13px;
}
.camera-device-select {
  flex: 1;
  min-width: 0;
}
.scan-video {
  width: 100%;
  max-height: 360px;
  border-radius: 8px;
  background: #000;
  border: 1px solid #2a3446;
}
.product-img-preview-still {
  object-fit: contain;
  display: block;
}
.scan-tip { color: #9aa7be; font-size: 13px; text-align: center; }

/* 编辑商品弹窗底部：一行内排完 OCR / 删除 / 取消 / 保存 */
.product-dialog-footer {
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
}
.product-dialog-footer__left,
.product-dialog-footer__right {
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.product-price-input {
  width: 100%;
  max-width: 100%;
}

@media (max-width: 768px) {
  .search-card :deep(.el-row) {
    row-gap: 8px;
  }
  .search-left-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }
  .search-left-row1 {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    width: 100%;
  }
  .search-input-control {
    width: 100%;
    max-width: none;
  }
  .search-filters-row {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 8px;
    width: 100%;
  }
  .search-filters-row .search-select-control {
    flex: 1;
    width: 0;
    min-width: 0;
    max-width: none;
  }
  .search-filters-row .search-filter-checkbox {
    flex: 1 0 100%;
    width: 100%;
    margin-top: 2px;
  }
  .search-actions {
    justify-content: stretch;
  }
  /* 非 iOS 小屏：保持纵向满宽按钮，与原先一致 */
  .search-actions:not(.search-actions--ios) {
    flex-direction: column;
    align-items: stretch;
  }
  .search-actions:not(.search-actions--ios) :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
  .search-actions--ios {
    margin-top: 4px;
  }
  .table-scroll {
    -webkit-overflow-scrolling: touch;
  }
  .row-actions {
    gap: 4px;
  }
  .row-actions :deep(.el-button) {
    padding: 5px 8px;
  }
  .add-btn {
    width: 100%;
  }
  .image-upload-area.large {
    height: 150px;
  }
  .product-dialog-footer {
    flex-wrap: nowrap;
    gap: 6px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 2px;
  }
  .product-dialog-footer :deep(.el-button) {
    flex-shrink: 0;
  }
  :deep(.product-dialog .el-dialog),
  :deep(.scan-dialog .el-dialog) {
    margin-top: 6vh !important;
  }
  :deep(.product-dialog .el-dialog__body),
  :deep(.scan-dialog .el-dialog__body) {
    padding: 14px;
  }
}
</style>

<!-- 无 scoped：须覆盖 App.vue 全局 `.el-input { width: 180px !important }`，否则标题与商品说明不同宽 -->
<style>
.product-dialog .listing-field-fullwidth.el-input {
  width: 100% !important;
  max-width: 100%;
}

.product-dialog .product-price-input {
  width: 100% !important;
  max-width: 100%;
}

.inventory-inline-select {
  width: 100% !important;
}

.inventory-inline-select-popper {
  min-width: 120px !important;
}

.product-type-cascader-popper .el-cascader-menu {
  height: 300px !important;
}

.product-type-cascader-popper .el-cascader-menu__wrap {
  height: 300px !important;
  max-height: 300px !important;
}

.product-type-cascader-popper .el-scrollbar__wrap {
  height: 300px !important;
  max-height: 300px !important;
}

.product-type-cascader-popper .el-cascader-menu__list {
  min-height: 300px !important;
}

.listing-pick-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.listing-pick-count {
  font-size: 13px;
  color: #67C23A;
  font-weight: 600;
  margin-right: 4px;
}
/* 选择模式下：选中行整行浅绿色覆盖（含固定列），80% 透明（alpha 0.2） */
.el-table tr.listing-pick-row-selected > td.el-table__cell {
  background-color: rgba(103, 194, 58, 0.2) !important;
  cursor: pointer;
}
.el-table tr.listing-pick-row-selected:hover > td.el-table__cell,
.el-table tr.listing-pick-row-selected.hover-row > td.el-table__cell {
  background-color: rgba(103, 194, 58, 0.32) !important;
}
.el-table tbody tr.listing-pick-row-disabled {
  cursor: not-allowed !important;
  opacity: 0.55;
}
/* 选择模式下，整张表行的鼠标指针变为可点击 */
.listing-pick-mode-active .el-table tbody tr {
  cursor: pointer;
}

/* 库存为 0 但仍有在售：与「在售商品」页相同的标红行（顶置由 sortedInventoryList 排序保证） */
.el-table tr.on-sale-stock-alert-row {
  --el-table-tr-bg-color: #3a1517;
}
.el-table tr.on-sale-stock-alert-row > td.el-table__cell {
  background-color: #3a1517 !important;
}
.el-table tr.on-sale-stock-alert-row:hover > td.el-table__cell {
  background-color: #4a1a1d !important;
}
.el-table tr.on-sale-stock-alert-row td.el-table__cell .cell {
  color: #ffd6d9;
  font-weight: 600;
}

/* 组合商品弹窗：与全局暗色对话框一致，组成行内展示正面缩略图 */
.combined-product-dialog .combined-product-items {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.combined-product-dialog .combined-product-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #28354a;
  border-radius: 8px;
  background: #18233a;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.2) inset;
}
.combined-product-dialog .combined-product-item__thumb {
  flex-shrink: 0;
  width: 56px;
  height: 56px;
}
.combined-product-dialog .combined-product-item__img {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  border: 1px solid #28354a;
  overflow: hidden;
  display: block;
}
.combined-product-dialog .combined-product-item__img :deep(.el-image__inner) {
  object-fit: cover;
}
.combined-product-dialog .combined-product-item__thumb-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  font-size: 12px;
  color: #64748b;
  background: #131c2f;
}
.combined-product-dialog .combined-product-item__thumb-placeholder {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  border: 1px dashed #3d4d66;
  background: #131c2f;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #64748b;
  text-align: center;
  line-height: 1.25;
  padding: 2px;
  box-sizing: border-box;
}
.combined-product-dialog .combined-product-item__main {
  flex: 1 1 auto;
  min-width: 0;
}
.combined-product-dialog .combined-product-item__name {
  font-weight: 600;
  color: #e6edf7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.combined-product-dialog .combined-product-item__meta {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}
.combined-product-dialog .combined-product-item__qty {
  width: 96px;
  flex: 0 0 auto;
}

/* 出品自动化全屏等待（teleport 到 body，须无 scoped；黑色主题） */
.listing-post-overlay.listing-post-overlay--dark {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(6px);
}
.listing-post-overlay--dark .listing-post-overlay__box {
  min-width: 280px;
  max-width: min(440px, 92vw);
  padding: 28px 32px;
  background: linear-gradient(165deg, #1c1c1f 0%, #121214 100%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  text-align: center;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.04) inset,
    0 20px 50px rgba(0, 0, 0, 0.65);
}
.listing-post-overlay--dark .listing-post-overlay__icon {
  color: #94a3b8;
}
.listing-post-overlay--dark .listing-post-overlay__title {
  margin-top: 14px;
  font-size: 17px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: 0.02em;
}
.listing-post-overlay--dark.listing-post-overlay--failed .listing-post-overlay__title {
  color: #f87171;
}
.listing-post-overlay--dark.listing-post-overlay--failed .listing-post-overlay__step {
  color: #cbd5e1;
}
.listing-post-overlay--dark .listing-post-overlay__step {
  margin-top: 10px;
  font-size: 14px;
  color: #94a3b8;
  line-height: 1.55;
  word-break: break-word;
}
</style>
