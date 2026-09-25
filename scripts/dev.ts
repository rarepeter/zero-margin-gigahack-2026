export {};

const children = [
  Bun.spawn(['bun', '--watch', 'server/index.ts'], { stdout: 'inherit', stderr: 'inherit' }),
  Bun.spawn(['bun', 'x', 'vite'], { stdout: 'inherit', stderr: 'inherit' }),
];
function stop() { for (const child of children) child.kill(); }
process.on('SIGINT', () => { stop(); process.exit(0); });
process.on('SIGTERM', () => { stop(); process.exit(0); });
const code = await Promise.race(children.map(child => child.exited));
stop();
process.exit(code);
