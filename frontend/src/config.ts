/**
 * 前端配置常量。
 */

// API 配置
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// 轮询配置
export const POLLING_INITIAL_INTERVAL = 1000;
export const POLLING_MAX_INTERVAL = 30000;
export const POLLING_BACKOFF_FACTOR = 1.5;

// 文件上传配置
export const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB
export const ALLOWED_FILE_EXTENSIONS = ['.pdf', '.txt', '.md', '.doc', '.docx'];

// 分页配置
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;

// 防抖配置
export const DEBOUNCE_DELAY = 300;
