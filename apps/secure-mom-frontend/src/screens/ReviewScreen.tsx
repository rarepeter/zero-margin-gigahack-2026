import { BottomBar } from '../components/review/BottomBar';
import { SummaryPane } from '../components/review/SummaryPane';
import { TranscriptPane } from '../components/review/TranscriptPane';

/** Transcript on the left, editable minutes on the right. */
export function ReviewScreen() {
  return (
    <>
      <div className="board">
        <TranscriptPane focus={null} />
        <SummaryPane />
      </div>
      <BottomBar />
    </>
  );
}
