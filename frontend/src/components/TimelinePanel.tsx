import { METRICS, metricHasData } from "../dashboard";
import type { Snapshot, Timeseries } from "../types";
import { Card } from "../util";
import { MetricChart } from "./MetricChart";

export function TimelinePanel({ snap, data }: { snap: Snapshot; data: Timeseries | null }) {
  const metrics = data ? METRICS.filter((metric) => metricHasData(snap, metric, data)) : [];
  return <Card title="All weather metrics">
    {data && metrics.length > 0 ? <div className="space-y-4">{metrics.map((metric) => <MetricChart key={metric.id} snap={snap} metric={metric} data={data} compact />)}</div>
      : <p className="text-sm text-ink2">Chart data is unavailable for this snapshot.</p>}
  </Card>;
}
