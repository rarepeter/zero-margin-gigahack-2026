import { useApp } from '../../state/store';

export function Toast() {
  const { s } = useApp();
  return <div className="toast" role="status" hidden={!s.toast}>{s.toast}</div>;
}
