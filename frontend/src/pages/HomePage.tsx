/**
 * 首页
 */
import { Box, Typography, Paper, Stack, Chip } from '@mui/material';
import { PageHeader } from '../components/ui';
import StorageIcon from '@mui/icons-material/Storage';
import ChatIcon from '@mui/icons-material/Chat';
import SearchIcon from '@mui/icons-material/Search';
import AssessmentIcon from '@mui/icons-material/Assessment';

const features = [
  {
    icon: StorageIcon,
    title: '多知识库管理',
    description: '创建和管理多个知识库，支持文档上传和知识索引',
  },
  {
    icon: ChatIcon,
    title: '智能问答代理',
    description: '基于知识库的智能问答，提供准确的答案和引用来源',
  },
  {
    icon: SearchIcon,
    title: '深度研究',
    description: '深入研究复杂问题，生成详细的研究报告',
  },
  {
    icon: AssessmentIcon,
    title: '对比评测',
    description: '评测不同配置下的问答效果，优化知识代理性能',
  },
];

export function HomePage() {
  return (
    <Box>
      <PageHeader
        title="多知识库知识代理"
        subtitle="基于 RAG 技术的智能知识问答系统"
      />

      <Stack spacing={3}>
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            功能特性
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 2,
              mt: 2,
            }}
          >
            {features.map(({ icon: Icon, title, description }) => (
              <Paper
                key={title}
                variant="outlined"
                sx={{
                  p: 2,
                  display: 'flex',
                  gap: 2,
                  alignItems: 'flex-start',
                }}
              >
                <Box
                  sx={{
                    p: 1,
                    borderRadius: 1,
                    bgcolor: 'primary.50',
                    color: 'primary.main',
                  }}
                >
                  <Icon />
                </Box>
                <Box>
                  <Typography fontWeight={500}>{title}</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    {description}
                  </Typography>
                </Box>
              </Paper>
            ))}
          </Box>
        </Paper>

        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            技术栈
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            <Chip label="React 18" size="small" />
            <Chip label="TypeScript" size="small" />
            <Chip label="Material UI" size="small" />
            <Chip label="React Query" size="small" />
            <Chip label="FastAPI" size="small" />
            <Chip label="LangChain" size="small" />
            <Chip label="Milvus" size="small" />
          </Stack>
        </Paper>
      </Stack>
    </Box>
  );
}
