import { Outlet } from 'react-router-dom';
import { Nav } from './Nav';

export function Layout() {
  return (
    <div>
      <Nav />
      <main style={{ maxWidth: 1080, margin: '0 auto' }}>
        <Outlet />
      </main>
    </div>
  );
}
