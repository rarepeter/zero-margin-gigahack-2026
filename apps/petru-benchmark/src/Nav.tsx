import { AudioLines, FileText, Target } from 'lucide-react';

export type Tab = 'asr' | 'accuracy' | 'mom';
export const tabFromHash = (): Tab => location.hash.startsWith('#/mom') ? 'mom' : location.hash.startsWith('#/accuracy') ? 'accuracy' : 'asr';

const tabs = [
  { id: 'asr', href: '#/', icon: AudioLines, title: 'Speech to text', subtitle: 'ASR side by side' },
  { id: 'accuracy', href: '#/accuracy', icon: Target, title: 'ASR accuracy', subtitle: 'Graded vs. your transcript' },
  { id: 'mom', href: '#/mom', icon: FileText, title: 'Minutes of Meeting', subtitle: 'LLM models' },
] as const satisfies readonly { id: Tab; href: string; icon: typeof AudioLines; title: string; subtitle: string }[];

// Switches between the benchmarks. Each benchmark keeps its own sidebar history.
export function BenchmarkNav({ active }: { active: Tab }) {
  return <nav className="bench-nav" aria-label="Benchmarks">
    {tabs.map(tab => <a key={tab.id} href={tab.href} className={active === tab.id ? 'active' : ''} aria-current={active === tab.id ? 'page' : undefined}><tab.icon size={15} /><span>{tab.title}<small>{tab.subtitle}</small></span></a>)}
  </nav>;
}
