/**
 * MD3 动画工具函数
 * 提供统一的动画配置和辅助函数
 */

// ============================================================================
// MD3 标准 Easing 曲线
// ============================================================================

export const md3Easing = {
  /** 标准缓动 - 适用于大多数过渡 */
  standard: 'cubic-bezier(0.2, 0, 0, 1)',
  /** 标准减速 - 元素进入视图 */
  standardDecelerate: 'cubic-bezier(0, 0, 0, 1)',
  /** 标准加速 - 元素离开视图 */
  standardAccelerate: 'cubic-bezier(0.3, 0, 1, 1)',
  /** 强调缓动 - 重要过渡 */
  emphasized: 'cubic-bezier(0.2, 0, 0, 1)',
  /** 强调减速 - 重要元素进入 */
  emphasizedDecelerate: 'cubic-bezier(0.05, 0.7, 0.1, 1)',
  /** 强调加速 - 重要元素离开 */
  emphasizedAccelerate: 'cubic-bezier(0.3, 0, 0.8, 0.15)',
} as const;

// ============================================================================
// MD3 标准时长 (毫秒)
// ============================================================================

export const md3Duration = {
  short1: 50,
  short2: 100,
  short3: 150,
  short4: 200,
  medium1: 250,
  medium2: 300,
  medium3: 350,
  medium4: 400,
  long1: 450,
  long2: 500,
  long3: 550,
  long4: 600,
} as const;

// ============================================================================
// 辅助函数
// ============================================================================

/**
 * 计算列表项交错动画延迟
 * @param index 列表项索引
 * @param baseDelay 基础延迟（毫秒）
 * @param maxDelay 最大延迟上限（毫秒）
 */
export function staggerDelay(
  index: number,
  baseDelay = 50,
  maxDelay = 300
): number {
  return Math.min(index * baseDelay, maxDelay);
}

/**
 * 生成 CSS transition 字符串
 * @param properties 需要过渡的属性列表
 * @param duration 持续时间（毫秒）
 * @param easing 缓动函数
 */
export function createTransition(
  properties: string[],
  duration: number = md3Duration.medium2,
  easing: string = md3Easing.standard
): string {
  return properties.map((prop) => `${prop} ${duration}ms ${easing}`).join(', ');
}

/**
 * 生成列表项动画样式
 * @param index 列表项索引
 * @param isVisible 是否可见
 */
export function getStaggerItemStyle(
  index: number,
  isVisible: boolean
): React.CSSProperties {
  const delay = staggerDelay(index);

  return {
    opacity: isVisible ? 1 : 0,
    transform: isVisible ? 'translateY(0)' : 'translateY(16px)',
    transition: `opacity ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms, transform ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms`,
  };
}

// ============================================================================
// CSS Keyframes 定义（供 CSS-in-JS 使用）
// ============================================================================

export const keyframes = {
  fadeIn: {
    from: { opacity: 0 },
    to: { opacity: 1 },
  },
  fadeInUp: {
    from: { opacity: 0, transform: 'translateY(16px)' },
    to: { opacity: 1, transform: 'translateY(0)' },
  },
  fadeInDown: {
    from: { opacity: 0, transform: 'translateY(-16px)' },
    to: { opacity: 1, transform: 'translateY(0)' },
  },
  scaleIn: {
    from: { opacity: 0, transform: 'scale(0.95)' },
    to: { opacity: 1, transform: 'scale(1)' },
  },
  shimmer: {
    '0%': { backgroundPosition: '-200% 0' },
    '100%': { backgroundPosition: '200% 0' },
  },
} as const;
