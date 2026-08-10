import { onMounted, onUnmounted, ref } from 'vue'

/**
 * 全站唯一的手机端断点。CSS 里的 `@media (max-width: 768px)` 必须用同一个数：
 * 两边不一致时，恰好落在断点上的设备会一半按手机、一半按电脑渲染。
 */
export const MOBILE_MEDIA_QUERY = '(max-width: 768px)'

/**
 * 响应式的「当前是不是手机宽度」。
 *
 * 用 matchMedia 而不是 resize 监听：横竖屏切换、安卓分屏、手机浏览器工具栏
 * 显隐都会触发 resize，但只有跨过断点那一次才需要重排，matchMedia 天然只在
 * 跨断点时回调一次。
 */
export function useIsMobile() {
  const isMobile = ref(
    typeof window !== 'undefined' && window.matchMedia(MOBILE_MEDIA_QUERY).matches
  )
  let mq = null

  function sync() {
    if (mq) isMobile.value = mq.matches
  }

  onMounted(() => {
    mq = window.matchMedia(MOBILE_MEDIA_QUERY)
    sync()
    mq.addEventListener('change', sync)
  })

  onUnmounted(() => {
    mq?.removeEventListener('change', sync)
    mq = null
  })

  return isMobile
}
