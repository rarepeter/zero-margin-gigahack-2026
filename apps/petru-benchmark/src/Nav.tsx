import { AudioLines, FileText } from 'lucide-react';

export type Tab = 'asr' | 'mom';
export const tabFromHash = (): Tab => (location.hash.startsWith('#/mom') ? 'mom' : 'asr');

// Switches between the two benchmarks. Each benchmark keeps its own sidebar history.
export function BenchmarkNav({ active }: { active: Tab }) {
  return <nav className="bench-nav" aria-label="Benchmarks">
    <a href="#/" className={active === 'asr' ? 'active' : ''} aria-current={active === 'asr' ? 'page' : undefined}><AudioLines size={15} /><span>Speech to text<small>ASR models</small></span></a>
    <a href="#/mom" className={active === 'mom' ? 'active' : ''} aria-current={active === 'mom' ? 'page' : undefined}><FileText size={15} /><span>Minutes of Meeting<small>LLM models</small></span></a>
  </nav>;
}
