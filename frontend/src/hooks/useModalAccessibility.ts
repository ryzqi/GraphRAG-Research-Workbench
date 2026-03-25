import { useEffect, useRef, useCallback } from 'react';

/**
 * 模态框可访问性 Hook，提供 ESC 关闭和焦点捕获。
 */
export function useModalAccessibility(
  isOpen: boolean,
  onClose: () => void
) {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<Element | null>(null);

  // 按 ESC 键关闭。
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    },
    [isOpen, onClose]
  );

  useEffect(() => {
    if (isOpen) {
      // 保存当前焦点元素
      previousActiveElement.current = document.activeElement;
      // 聚焦到模态框
      modalRef.current?.focus();
      // 添加键盘事件监听
      document.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      // 恢复焦点
      if (!isOpen && previousActiveElement.current instanceof HTMLElement) {
        previousActiveElement.current.focus();
      }
    };
  }, [isOpen, handleKeyDown]);

  return { modalRef };
}
