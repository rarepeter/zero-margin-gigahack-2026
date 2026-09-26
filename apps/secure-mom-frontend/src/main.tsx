import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// Self-hosted fonts: the app must work fully offline (no Google Fonts).
import '@fontsource/montserrat/400.css';
import '@fontsource/montserrat/500.css';
import '@fontsource/montserrat/600.css';
import '@fontsource/montserrat/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './styles/app.css';
import './styles/react.css';
import { App } from './App';
import { AppProvider } from './state/store';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
