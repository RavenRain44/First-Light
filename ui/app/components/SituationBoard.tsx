import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer } from 'react-leaflet'
import { CloudLightning, LocateFixed, RefreshCw, Satellite } from 'lucide-react'
import type { FeatureCollection } from 'geojson'
import type { Facility } from '../types'

interface Props {
  facilities: Facility[]
  selectedId: string
  alerts: FeatureCollection | null
  liveError: string
  busy: boolean
  onSelect: (id: string) => void
  onRefresh: () => void
  onTeleport: () => void
}

const postureColors: Record<string, string> = {
  NORMAL: '#46c28b',
  TELEWORK_OPTION: '#e8c75c',
  DELAYED_ARRIVAL: '#f39a4a',
  EARLY_DISMISSAL: '#f07552',
  CLOSED: '#ef6262',
}

export default function SituationBoard({ facilities, selectedId, alerts, liveError, busy, onSelect, onRefresh, onTeleport }: Props) {
  const selected = facilities.find((item) => item.id === selectedId) || facilities[0]
  return (
    <section className="page situation-page">
      <div className="page-heading split-heading">
        <div>
          <p className="eyebrow">National situation board</p>
          <h1>Weather context, already assembled.</h1>
          <p>Six service centers. One decision model. Live federal weather sources stay traceable.</p>
        </div>
        <div className="action-row">
          <button className="button secondary" onClick={onRefresh} disabled={busy}>
            <RefreshCw size={16} className={busy ? 'spin' : ''} /> Refresh live data
          </button>
          <button className="button primary" onClick={onTeleport} disabled={busy}>
            <LocateFixed size={16} /> Teleport to live alert
          </button>
        </div>
      </div>

      {liveError && <div className="notice error"><Satellite size={18} /> Live source failed visibly: {liveError}</div>}

      <div className="situation-grid">
        <div className="map-shell">
          <MapContainer center={[38.5, -97]} zoom={4} minZoom={3} className="map">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {alerts && (
              <GeoJSON
                data={alerts}
                style={{ color: '#f17e5d', weight: 1, fillColor: '#ee6b50', fillOpacity: 0.12 }}
              />
            )}
            {facilities.map((facility) => (
              <CircleMarker
                key={facility.id}
                center={[facility.lat, facility.lon]}
                radius={facility.id === selectedId ? 12 : 8}
                pathOptions={{ color: '#071b20', weight: 2, fillColor: postureColors[facility.recommendation.posture], fillOpacity: 1 }}
                eventHandlers={{ click: () => onSelect(facility.id) }}
              >
                <Popup>
                  <strong>{facility.city}, {facility.state}</strong><br />
                  {facility.recommendation.posture.replaceAll('_', ' ')}
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="map-legend">
            {Object.entries(postureColors).map(([key, color]) => (
              <span key={key}><i style={{ background: color }} />{key.replaceAll('_', ' ').toLowerCase()}</span>
            ))}
          </div>
        </div>

        <aside className="facility-panel">
          <div className="panel-title"><CloudLightning size={18} /> Facility posture</div>
          <div className="facility-list">
            {facilities.map((facility) => (
              <button key={facility.id} className={`facility-row ${facility.id === selectedId ? 'selected' : ''}`} onClick={() => onSelect(facility.id)}>
                <span className="posture-dot" style={{ background: postureColors[facility.recommendation.posture] }} />
                <span className="facility-name"><strong>{facility.city}, {facility.state}</strong><small>{facility.region}</small></span>
                <span className="facility-status">{facility.recommendation.posture.replaceAll('_', ' ')}</span>
              </button>
            ))}
          </div>
          {selected && (
            <div className="selected-summary">
              <span className={`mode mode-${selected.recommendation.data_mode}`}>{selected.recommendation.data_mode} data</span>
              <strong>{selected.recommendation.active_alerts} alert signal{selected.recommendation.active_alerts === 1 ? '' : 's'}</strong>
              <p>Confidence: {selected.recommendation.confidence.level}. Select Decision to inspect every threshold and source.</p>
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
