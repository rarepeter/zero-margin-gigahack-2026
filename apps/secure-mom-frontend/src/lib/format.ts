export const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
export const minSec = (sec: number) => `${Math.floor(sec / 60)} min ${String(Math.floor(sec % 60)).padStart(2, '0')} s`;
export const hhmmss = (sec: number) => [sec / 3600, (sec / 60) % 60, sec % 60].map((x) => String(Math.floor(x)).padStart(2, '0')).join(':');
export const pct = (x: number) => `${Math.round(x * 100)}%`;
