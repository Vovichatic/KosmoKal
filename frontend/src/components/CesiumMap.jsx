import { useEffect, useMemo, useState } from 'react';
import { CameraFlyTo, Entity, ImageryLayer, Viewer } from 'resium';
import {
  Cartesian2,
  Cartesian3,
  Color,
  DistanceDisplayCondition,
  NearFarScalar,
  UrlTemplateImageryProvider,
} from 'cesium';

const earthProvider = new UrlTemplateImageryProvider({
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  credit: '© OpenStreetMap contributors',
  maximumLevel: 18,
});

const toCartesian = (point) => Cartesian3.fromDegrees(point.lon, point.lat, point.alt_km * 1000);
const formatUtc = (value) => new Date(value).toLocaleString('ru-RU', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC',
});

function TrackLine({ points, color, width = 2 }) {
  const positions = useMemo(() => points.map(toCartesian), [points]);
  if (positions.length < 2) return null;
  return <Entity polyline={{ positions, width, material: color }} />;
}

export default function CesiumMap({ orbit, selectedWindow }) {
  const track = useMemo(() => orbit?.track || [], [orbit?.track]);
  const [cursor, setCursor] = useState(() => {
    if (!orbit?.track?.length) return 0;
    const reference = new Date(orbit.reference_time).getTime();
    return orbit.track.reduce((best, item, index) => (
      Math.abs(new Date(item.time).getTime() - reference) < Math.abs(new Date(orbit.track[best].time).getTime() - reference)
        ? index : best
    ), 0);
  });
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing || track.length < 2) return undefined;
    const timer = window.setInterval(() => {
      setCursor((value) => (value >= track.length - 1 ? 0 : value + 1));
    }, 160);
    return () => window.clearInterval(timer);
  }, [playing, track.length]);

  const segments = useMemo(() => {
    if (!track.length) return { before: [], selected: [], after: [] };
    if (!selectedWindow) {
      const reference = new Date(orbit.reference_time).getTime();
      return {
        before: track.filter((item) => new Date(item.time).getTime() <= reference),
        selected: [],
        after: track.filter((item) => new Date(item.time).getTime() >= reference),
      };
    }
    const start = selectedWindow ? new Date(selectedWindow.start).getTime() : new Date(orbit.start).getTime();
    const end = selectedWindow
      ? start + Number(selectedWindow.duration_h) * 3600_000
      : new Date(orbit.end).getTime();
    return {
      before: track.filter((item) => new Date(item.time).getTime() <= start),
      selected: track.filter((item) => {
        const time = new Date(item.time).getTime();
        return time >= start && time <= end;
      }),
      after: track.filter((item) => new Date(item.time).getTime() >= end),
    };
  }, [orbit, selectedWindow, track]);

  const point = track[cursor] || orbit?.current;
  const sourceIsFallback = orbit?.source?.is_fallback;

  return (
    <div className="absolute inset-0 overflow-hidden bg-[#05070b]">
      <Viewer
        full
        timeline={false}
        animation={false}
        baseLayerPicker={false}
        geocoder={false}
        homeButton={false}
        navigationHelpButton={false}
        sceneModePicker={false}
        infoBox={false}
        selectionIndicator={false}
        imageryProvider={false}
      >
        <CameraFlyTo destination={Cartesian3.fromDegrees(20, 15, 21_000_000)} duration={0} once />
        <ImageryLayer imageryProvider={earthProvider} brightness={0.62} contrast={1.18} saturation={0.72} />
        <TrackLine points={segments.before} color={Color.fromCssColorString('#64748b').withAlpha(0.55)} />
        <TrackLine points={segments.selected} color={Color.fromCssColorString('#f59e0b').withAlpha(0.98)} width={4} />
        <TrackLine points={segments.after} color={Color.fromCssColorString('#22d3ee').withAlpha(0.68)} />
        {point && (
          <Entity
            position={toCartesian(point)}
            name="Международная космическая станция"
            point={{
              pixelSize: 13,
              color: Color.WHITE,
              outlineColor: Color.fromCssColorString('#f59e0b'),
              outlineWidth: 5,
              scaleByDistance: new NearFarScalar(1.5e6, 1.2, 2.0e7, 0.55),
            }}
            label={{
              text: 'МКС · 25544',
              font: '600 13px Inter, sans-serif',
              fillColor: Color.WHITE,
              outlineColor: Color.BLACK,
              outlineWidth: 3,
              pixelOffset: new Cartesian2(0, -25),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 1.7e7),
            }}
          />
        )}
      </Viewer>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 bg-gradient-to-b from-black/75 to-transparent p-6">
        <div>
          <div className="mb-1 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.22em] text-cyan-300">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-300 shadow-[0_0_12px_#67e8f9]" />
            Орбитальный контур МКС
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Траектория над Землёй</h1>
          <p className="mt-1 text-xs text-slate-400">SGP4 · высота линии соответствует расчётной орбите</p>
        </div>
        {point && (
          <div className="rounded-lg border border-white/10 bg-black/55 px-4 py-3 text-right font-mono backdrop-blur-md">
            <div className="text-[9px] uppercase tracking-widest text-slate-400">Координаты на шкале</div>
            <div className="mt-1 text-sm text-white">{point.lat.toFixed(3)}° · {point.lon.toFixed(3)}°</div>
            <div className="text-[10px] text-cyan-300">{point.alt_km.toFixed(1)} км</div>
          </div>
        )}
      </div>

      {orbit && (
        <div className="absolute inset-x-5 bottom-5 rounded-xl border border-white/10 bg-[#0b1018]/88 p-4 text-slate-200 shadow-2xl backdrop-blur-xl">
          <div className="mb-3 flex items-center justify-between gap-4">
            <div className="flex items-center gap-5 text-[9px] uppercase tracking-wider text-slate-400">
              <span><i className="mr-1.5 inline-block h-0.5 w-4 bg-slate-500" />до окна</span>
              <span><i className="mr-1.5 inline-block h-0.5 w-4 bg-amber-400" />выбранное окно</span>
              <span><i className="mr-1.5 inline-block h-0.5 w-4 bg-cyan-400" />дальше</span>
            </div>
            <div className={`text-[9px] uppercase tracking-wider ${sourceIsFallback ? 'text-amber-400' : 'text-emerald-400'}`}>
              {sourceIsFallback ? 'резервные элементы' : 'орбита актуальна'}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => setPlaying((value) => !value)} className="h-8 w-8 shrink-0 rounded-full bg-amber-400 text-xs font-black text-black hover:bg-amber-300">
              {playing ? 'Ⅱ' : '▶'}
            </button>
            <input
              aria-label="Время на орбитальной траектории"
              type="range"
              min="0"
              max={Math.max(0, track.length - 1)}
              value={Math.min(cursor, Math.max(0, track.length - 1))}
              onChange={(event) => { setPlaying(false); setCursor(Number(event.target.value)); }}
              className="orbit-range min-w-0 flex-1"
            />
            <div className="w-40 shrink-0 text-right font-mono text-[10px]">
              <div className="text-white">{point ? formatUtc(point.time) : '—'} UTC</div>
              <div className="mt-0.5 truncate text-slate-500" title={orbit.source?.label}>{orbit.source?.label}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
