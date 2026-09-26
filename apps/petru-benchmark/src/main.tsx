import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { MomBenchmark } from './MomBenchmark';
import { tabFromHash } from './Nav';
import './styles.css';

function Root() {
  const [tab, setTab] = useState(tabFromHash);
  useEffect(() => {
    const sync = () => setTab(tabFromHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);
  return tab === 'mom' ? <MomBenchmark /> : <App />;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Root /></React.StrictMode>);
