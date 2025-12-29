import { NavLink } from 'react-router-dom';

const linkStyle = ({ isActive }: { isActive: boolean }) => ({
  padding: '8px 10px',
  borderRadius: 8,
  background: isActive ? '#111827' : 'transparent',
  color: isActive ? '#ffffff' : '#111827',
});

export function Nav() {
  return (
    <nav
      style={{
        display: 'flex',
        gap: 8,
        padding: 12,
        borderBottom: '1px solid #e5e7eb',
        background: '#ffffff',
        position: 'sticky',
        top: 0,
      }}
    >
      <NavLink to="/" style={linkStyle} end>
        首页
      </NavLink>
      <NavLink to="/kb-chat" style={linkStyle}>
        知识库代理
      </NavLink>
      <NavLink to="/general-chat" style={linkStyle}>
        全能代理
      </NavLink>
      <NavLink to="/research" style={linkStyle}>
        深度研究
      </NavLink>
      <NavLink to="/knowledge-bases" style={linkStyle}>
        知识库管理
      </NavLink>
      <NavLink to="/extensions" style={linkStyle}>
        扩展管理
      </NavLink>
      <NavLink to="/evaluations" style={linkStyle}>
        对比评测
      </NavLink>
      <NavLink to="/feedback" style={linkStyle}>
        反馈管理
      </NavLink>
    </nav>
  );
}
