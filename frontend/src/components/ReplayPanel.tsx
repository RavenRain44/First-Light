import type { Snapshot } from "../types";
import { Card } from "../util";

export function ReplayPanel(_props: { onSnapshot: (s: Snapshot) => void; busy: boolean; setBusy: (b: boolean) => void; current?: Snapshot | null }) {
  return <Card title="ReplayPanel"><p className="text-sm text-ink2">Coming in a later phase.</p></Card>;
}
