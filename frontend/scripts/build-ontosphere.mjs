import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const cwd = fileURLToPath(new URL('../ontosphere/', import.meta.url));
if (!existsSync(new URL('../ontosphere/node_modules/', import.meta.url))) {
  console.error('请先执行 npm --prefix ontosphere ci 安装原版编辑器依赖。');
  process.exit(1);
}
const command = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const result = spawnSync(command, ['run', 'build', '--', '--outDir', '../public/ontosphere', '--emptyOutDir'], {
  cwd, env: { ...process.env, VITE_BASE_PATH: '/ontosphere/' }, stdio: 'inherit', shell: process.platform === 'win32',
});
process.exit(result.status ?? 1);
