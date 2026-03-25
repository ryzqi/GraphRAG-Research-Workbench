/**
 * 输入编排器组件
 * Gemini 风格浮动输入框，支持自动增高和附件上传
 */
import { useState, useRef, useCallback, type KeyboardEvent, type ChangeEvent } from 'react';
import {
  Box,
  IconButton,
  Paper,
  Tooltip,
  Typography,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  CircularProgress,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { ACCEPTED_FILE_TYPES, SUPPORTED_FILE_TYPES_LABEL } from '../../utils/fileValidation';

// 视觉上更接近单行输入框的高度（用于“垂直居中”的观感）
const MIN_TEXTAREA_HEIGHT = 36;
const MAX_TEXTAREA_HEIGHT = 200;

interface InputComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onFileUpload?: (file: File) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
  loading?: boolean;
  showAttachment?: boolean;
  showShortcutHint?: boolean;
}

export function InputComposer({
  value,
  onChange,
  onSend,
  onFileUpload,
  disabled = false,
  placeholder = '输入消息...',
  loading = false,
  showAttachment = false,
  showShortcutHint = true,
}: InputComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [uploading, setUploading] = useState(false);

  // 自动调整高度
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const newHeight = Math.min(
        Math.max(textarea.scrollHeight, MIN_TEXTAREA_HEIGHT),
        MAX_TEXTAREA_HEIGHT
      );
      textarea.style.height = `${newHeight}px`;
    }
  }, []);

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
    adjustHeight();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) {
        onSend();
      }
    }
  };

  const handleSend = () => {
    if (!disabled && value.trim()) {
      onSend();
      // 重置高度
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleAttachClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleAttachClose = () => {
    setAnchorEl(null);
  };

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !onFileUpload) return;

    setUploading(true);
    handleAttachClose();

    try {
      await onFileUpload(file);
    } finally {
      setUploading(false);
      // 重置输入框
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
    handleAttachClose();
  };

  const isDisabled = disabled || loading || uploading;
  const canSend = !isDisabled && value.trim().length > 0;

  return (
    <Box
      sx={{
        animation: 'composerEnter 300ms cubic-bezier(0.2, 0, 0, 1)',
        '@keyframes composerEnter': {
          from: {
            opacity: 0,
            transform: 'translateY(20px)',
          },
          to: {
            opacity: 1,
            transform: 'translateY(0)',
          },
        },
        '@media (prefers-reduced-motion: reduce)': {
          animation: 'none',
        },
      }}
    >
      <Paper
        elevation={0}
        sx={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 0.75,
          p: 1.1,
          borderRadius: '24px',
          // 毛玻璃效果
          bgcolor: (theme) =>
            theme.palette.mode === 'light' ? 'rgba(255, 255, 255, 0.8)' : 'rgba(30, 31, 34, 0.85)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          border: (theme) =>
            `1px solid ${theme.palette.mode === 'light' ? 'rgba(0, 0, 0, 0.08)' : 'rgba(255, 255, 255, 0.08)'}`,
          boxShadow: (theme) =>
            theme.palette.mode === 'light'
              ? '0 8px 32px rgba(0, 0, 0, 0.08)'
              : '0 8px 32px rgba(0, 0, 0, 0.3)',
        }}
      >
        {/* 附件按钮 */}
        {showAttachment && onFileUpload && (
          <>
            <Tooltip title="添加附件">
              <IconButton
                onClick={handleAttachClick}
                disabled={isDisabled}
                aria-label='添加附件'
                sx={{ color: 'text.secondary' }}
              >
                {uploading ? <CircularProgress size={20} /> : <AttachFileIcon />}
              </IconButton>
            </Tooltip>
            <Menu
              anchorEl={anchorEl}
              open={Boolean(anchorEl)}
              onClose={handleAttachClose}
              anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
              transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
            >
              <MenuItem onClick={triggerFileInput}>
                <ListItemIcon>
                  <UploadFileIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary="上传文件"
                  secondary={`支持 ${SUPPORTED_FILE_TYPES_LABEL}`}
                  secondaryTypographyProps={{ variant: 'caption' }}
                />
              </MenuItem>
            </Menu>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_FILE_TYPES}
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
          </>
        )}

        {/* 输入框 */}
        <Box
          component="textarea"
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isDisabled}
          rows={1}
          sx={{
            flex: 1,
            border: 'none',
            outline: 'none',
            resize: 'none',
            bgcolor: 'transparent',
            color: 'text.primary',
            fontSize: 14,
            lineHeight: 1.45,
            fontFamily: 'inherit',
            // 单行时通过固定最小高度 + 上下内边距实现“垂直居中”的视觉效果
            textAlign: 'left',
            minHeight: MIN_TEXTAREA_HEIGHT,
            maxHeight: MAX_TEXTAREA_HEIGHT,
            px: 1.25,
            py: 0.75,
            '&::placeholder': {
              color: 'text.secondary',
              opacity: 0.7,
            },
            '&:disabled': {
              opacity: 0.5,
              cursor: 'not-allowed',
            },
          }}
        />

        {/* 发送按钮 */}
        <Tooltip title="发送 (Enter)">
          <span>
            <IconButton
              onClick={handleSend}
              disabled={!canSend}
              aria-label='发送消息'
              sx={{
                bgcolor: canSend ? 'primary.main' : 'action.disabledBackground',
                color: canSend ? 'primary.contrastText' : 'text.disabled',
                '&:hover': {
                  bgcolor: canSend ? 'primary.main' : 'action.disabledBackground',
                  filter: canSend ? 'brightness(0.95)' : 'none',
                },
                '&.Mui-disabled': {
                  bgcolor: 'action.disabledBackground',
                  color: 'text.disabled',
                },
              }}
            >
              {loading ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
            </IconButton>
          </span>
        </Tooltip>
      </Paper>

      {/* 提示文字 */}
      {showShortcutHint && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', textAlign: 'center', mt: 1 }}
        >
          Enter 发送，Shift+Enter 换行
        </Typography>
      )}
    </Box>
  );
}
