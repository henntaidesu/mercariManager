import http from './http'

// OCR 识别 → /mercariV2/src/use_web/ocr/*
export const ocrApi = {
  ocrRegion: (base64Image) => http.post('/use_web/ocr/ocr-region', { image: base64Image })
}
