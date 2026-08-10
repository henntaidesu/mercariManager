<template>
  <el-config-provider :locale="elementLocale">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { ElConfigProvider } from 'element-plus'
import { elementLocale } from '@/i18n'
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root.dark {
  color-scheme: dark;
}

/* ===== 视口高度单位：一律用 var(--app-vh)，不要直接写 vh =====
   移动端（iPad / 手机）浏览器的地址栏、工具栏会遮住视口底部，而 1vh 取的是
   「工具栏全部收起」时的大视口，比实际可见区域高——按 100vh 定高的页面因此
   总比屏幕高出一截，必须往下拉才能看全；各家浏览器工具栏高度不同，多出来的
   那一截也不一样，这就是「不同浏览器打开高度不一样」的原因。
   dvh 取的是当前实际可见高度，浏览器自己会随工具栏显隐更新，天然自适应。
   不支持 dvh 的旧浏览器落回 vh，行为与改动前一致。 */
:root {
  --app-vh: 1vh;
}

@supports (height: 1dvh) {
  :root {
    --app-vh: 1dvh;
  }
}

/* 与暗色主题对齐：避免统计卡片、表格卡片出现浅色底 / 白屏 loading */
html.dark {
  --el-bg-color: #0b1220;
  --el-bg-color-page: #0b1220;
  --el-fill-color-blank: #131c2f;
  --el-fill-color-light: #18233a;
  --el-mask-color: rgba(11, 18, 32, 0.78);
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  background: #0b1220;
  color: #e5e7eb;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-thumb {
  background: #3a4456;
  border-radius: 3px;
}
::-webkit-scrollbar-track {
  background: transparent;
}

.page-title {
  color: #e6edf7 !important;
}

.el-card,
.el-dialog,
.el-table,
.el-input__wrapper,
.el-select__wrapper,
.el-textarea__inner {
  border-color: #2a3446 !important;
}

.el-card {
  background: #131c2f !important;
  color: #e6edf7;
}

.el-card__header {
  background: #161f33 !important;
  border-bottom: 1px solid #28354a !important;
  color: #e6edf7 !important;
}

.el-card__body {
  background: transparent !important;
  color: #e6edf7;
}

.el-loading-mask {
  background-color: var(--el-mask-color) !important;
}

.el-loading-mask .el-loading-spinner .path {
  stroke: #8fb8ff;
}

.el-table {
  --el-table-header-bg-color: #18233a;
  --el-table-tr-bg-color: #131c2f;
  --el-table-row-hover-bg-color: #1b2942;
  --el-table-border-color: #28354a;
  color: #d6deea;
}

.el-dialog {
  --el-dialog-bg-color: #131c2f;
}

.el-input,
.el-select,
.el-date-editor.el-input__wrapper,
.el-date-editor.el-input {
  width: 180px !important;
}

.el-range-editor.el-input__wrapper,
.el-date-editor--daterange {
  width: 180px !important;
  min-width: 180px !important;
}

/* ===== 手机端（iOS / Android）通用地基 =====
   全站共用，各页只在自己的 style.css 里写版式差异。断点统一 768px，
   与 JS 侧 useIsMobile() 的 matchMedia('(max-width: 768px)') 同一口径——
   两边不一致时，恰好 768px 宽的设备会一半按手机、一半按电脑渲染。 */

/* iOS 横竖屏切换时 Safari 会自行放大正文字号（text autosizing），
   页面里定好的 12/13px 在横屏下会变大，且各块放大比例并不一致 */
html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

/* 整个应用是 height:100% + 内部滚动，body 本身从不滚动；
   不禁掉链式滚动的话，安卓 Chrome 在列表顶端继续下拉会触发下拉刷新，
   把这个单页应用整页重载（resumeGuard.js 防的也是同一类意外重载） */
html,
body {
  overscroll-behavior: none;
}

/* 安卓点击时的灰色高亮块：各处已有自绘的 :active / hover 反馈 */
body {
  -webkit-tap-highlight-color: transparent;
}

@media (max-width: 768px) {
  /* iOS Safari 聚焦 font-size < 16px 的输入框时会强行放大整页，且失焦后不复位。
     所有输入类控件在手机上一律 16px——这是唯一可靠的规避方式。 */
  .el-input__inner,
  .el-input__wrapper,
  .el-textarea__inner,
  .el-select__wrapper,
  .el-select__placeholder,
  .el-input-number__decrease,
  .el-input-number__increase {
    font-size: 16px;
  }

  /* 上面给输入类控件写死了 180px；手机上窄容器（弹窗、卡片内表单）里会横向溢出。
     只放开 max-width，不动 min-width：把 min-width 归零会解除弹性项的
     auto 最小尺寸，控件在 nowrap 的筛选行里会被压成几十像素宽的碎条——
     正确做法是让那一行自己换行/纵向堆叠（见各页手机块），而不是允许压扁。 */
  .el-input,
  .el-select,
  .el-date-editor.el-input__wrapper,
  .el-date-editor.el-input,
  .el-range-editor.el-input__wrapper,
  .el-date-editor--daterange {
    max-width: 100% !important;
  }

  /* 固定像素宽的弹窗（400~720px）在 375px 屏上必然横向溢出；
     默认 15vh 的顶部留白在手机上也过于浪费。弹窗过高时由 Element 自己的
     遮罩层滚动（.el-overlay-dialog），这里不另加内层滚动，免得叠出两条滚动条 */
  .el-dialog {
    --el-dialog-margin-top: 5vh;
    width: 94vw !important;
    max-width: 94vw;
  }
  .el-message-box {
    width: 88vw !important;
    max-width: 88vw;
  }

  /* 弹窗里的表单一律改成「标签在上」。全站这些表单的 label-width 是
     78~120px，弹窗压到 94vw（约 352px）后标签一让，输入框只剩 200 出头，
     日文标签还会自己折行。等价于 label-position="top"，但不用逐个改模板——
     项目里本来就有好几处表单显式写着 top，且没有任何 inline 表单，
     所以这条不会拆散刻意并排的布局。
     标签宽度和内容缩进是 Element 直接写在元素 style 上的，只能 !important 顶掉。 */
  .el-dialog .el-form-item {
    display: block;
  }
  .el-dialog .el-form-item__label {
    width: auto !important;
    height: auto;
    justify-content: flex-start;
    text-align: left;
    line-height: 1.4;
    padding: 0 0 4px;
  }
  .el-dialog .el-form-item__content {
    margin-left: 0 !important;
  }
  /* 表单控件跟着满宽，别停在上面那条 180px 上。
     限定直接子元素：并排放两个控件的表单项都套了一层 div，不会被波及。 */
  .el-dialog .el-form-item__content > .el-input,
  .el-dialog .el-form-item__content > .el-select,
  .el-dialog .el-form-item__content > .el-cascader,
  .el-dialog .el-form-item__content > .el-date-editor,
  .el-dialog .el-form-item__content > .el-input-number {
    width: 100% !important;
    max-width: none !important;
  }

  /* 下拉/日期面板默认可以宽过屏幕，弹出后要横向拖才看得全 */
  .el-popper,
  .el-select__popper,
  .el-picker__popper {
    max-width: calc(100vw - 16px) !important;
  }

  /* 卡片内边距 20px 在 375px 屏上要吃掉整整 40px 可用宽度 */
  .el-card__body {
    padding: 12px;
  }
  .el-card__header {
    padding: 12px;
  }

  /* 表格在手机上一律靠横向滚动读全列，压紧行高与字号能少滚一大截；
     同时让横向滚动条常驻——触摸设备没有 hover，Element 默认淡出后
     用户看不出这里还能左右滑 */
  .el-table {
    font-size: 12px;
  }
  .el-table .cell {
    padding: 0 6px;
  }
  .el-table td.el-table__cell,
  .el-table th.el-table__cell {
    padding: 6px 0;
  }
  .el-table .el-scrollbar__bar.is-horizontal {
    opacity: 1;
    height: 5px;
  }

  /* 触摸屏没有真正的 hover：安卓上点过的行会一直「卡」在 hover 底色，
     看起来像被选中。改变量而不是写覆盖规则——Element 自己的
     `.el-table--enable-row-hover .el-table__body tr:hover>td` 选择器权重更高，
     照着写一条同形状的覆盖规则反而压不住。 */
  @media (hover: none) {
    .el-table {
      --el-table-row-hover-bg-color: transparent;
    }
  }

  /* 按钮/分页的最小可点面积：44px 是 iOS HIG、48dp 是 Material 的下限 */
  .el-button {
    min-height: 34px;
  }
  .el-pagination button,
  .el-pagination .el-pager li {
    min-width: 32px;
    height: 32px;
    line-height: 32px;
  }
}
</style>
