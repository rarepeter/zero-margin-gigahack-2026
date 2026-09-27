import { Sidebar } from './components/layout/Sidebar';
import { SecurityBar } from './components/layout/SecurityBar';
import { Toast } from './components/ui/Toast';
import { DoneScreen } from './screens/DoneScreen';
import { FailedScreen } from './screens/FailedScreen';
import { ProcessingScreen } from './screens/ProcessingScreen';
import { RecordingScreen } from './screens/RecordingScreen';
import { ReviewRestoreScreen } from './screens/ReviewRestoreScreen';
import { ReviewScreen } from './screens/ReviewScreen';
import { UploadScreen } from './screens/UploadScreen';
import { useApp, type Screen } from './state/store';

const SCREENS: Record<Screen, () => React.JSX.Element | null> = {
  upload: UploadScreen,
  recording: RecordingScreen,
  processing: ProcessingScreen,
  'restoring-review': ReviewRestoreScreen,
  failed: FailedScreen,
  review: ReviewScreen,
  done: DoneScreen,
};

export function App() {
  const { s } = useApp();
  const View = SCREENS[s.screen];
  const board = s.screen === 'review' || s.screen === 'processing';
  return (
    <>
      <div className="shell">
        <Sidebar />
        <div className="work">
          <SecurityBar />
          <main className={`main${board ? '' : ' solo'}`} id="app" aria-live="polite">
            <View />
          </main>
        </div>
      </div>
      <Toast />
    </>
  );
}
