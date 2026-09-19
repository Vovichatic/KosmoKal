const formatUtc = (value) => new Date(value).toLocaleTimeString('ru-RU', {
  hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
});
const percent = (value) => `${Math.round((value || 0) * 100)}%`;

function RiskBar({ value, threshold = 0.244 }) {
  const width = Math.min(100, Math.max(3, value * 100));
  return (
    <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-slate-500/20">
      <div className={`h-full rounded-full ${value >= threshold ? 'bg-orange-400' : 'bg-emerald-400'}`} style={{ width: `${width}%` }} />
      <div className="absolute inset-y-0 w-px bg-white/70" style={{ left: `${threshold * 100}%` }} />
    </div>
  );
}

function WindowCard({ window, label, selected, headerBg, textMuted, onSelect }) {
  const ml = window.ml_forecast;
  const risk = ml?.alert || window.weather_combined > 0.55;
  return (
    <button type="button" onClick={onSelect} className={`rounded-md border p-3 text-left transition-all hover:-translate-y-0.5 hover:border-[#f39c12]/50 ${selected ? 'border-[#f39c12]/70 bg-[#f39c12]/8 shadow-[0_0_20px_rgba(243,156,18,.08)]' : headerBg}`}>
      <div className="mb-2 flex items-start justify-between gap-3 border-b border-gray-500/20 pb-2">
        <div>
          <span className="text-[9px] font-bold uppercase tracking-wider">{label}</span>
          {window.on_pareto_front && <span className="ml-2 text-[8px] uppercase text-cyan-400">Парето</span>}
        </div>
        <span title={window.explanation} className={`text-[9px] font-bold uppercase ${risk ? 'text-orange-400' : 'text-emerald-400'}`}>{risk ? '⚠ внимание' : '● норма'}</span>
      </div>
      <p className="font-mono text-xs font-semibold">{formatUtc(window.start)} UTC · {window.duration_h} ч</p>
      <div className={`mt-3 grid grid-cols-3 gap-2 text-[9px] ${textMuted}`}>
        <div><span className="block text-[8px] uppercase">Доза-прокси</span><b>{window.dose_usv_proxy} мкЗв</b></div>
        <div><span className="block text-[8px] uppercase">Kp max</span><b>{window.kp_max.toFixed(1)}</b></div>
        <div><span className="block text-[8px] uppercase">Данные</span><b>{percent(window.completeness)}</b></div>
      </div>
      {ml && <div className="mt-3 rounded-sm border border-violet-400/20 bg-violet-400/5 p-2"><div className="flex justify-between text-[9px]"><span>CatBoost · Q99 / 6ч{ml.projection ? ` · ${ml.confidence}` : ''}</span><b>{percent(ml.probability)}</b></div><RiskBar value={ml.probability} threshold={ml.threshold} /></div>}
    </button>
  );
}

export default function ResultsDashboard({ results, isLoading, isProMode, isDarkTheme, selectedWindowStart, onSelectWindow }) {
  const bgClass = isDarkTheme ? 'bg-[#24262d] border-[#30333b]' : 'bg-white border-gray-200';
  const headerBg = isDarkTheme ? 'bg-[#1b1d22] border-[#30333b]' : 'bg-gray-100 border-gray-200';
  const textMain = isDarkTheme ? 'text-white' : 'text-gray-900';
  const textMuted = isDarkTheme ? 'text-[#8b91a0]' : 'text-gray-500';

  if (isLoading) return <div className={`flex w-full shrink-0 animate-pulse flex-col gap-4 rounded-md border p-6 ${bgClass}`}><div className="h-4 w-1/3 rounded bg-gray-500/20" /><div className="h-32 w-full rounded bg-gray-500/10" /></div>;
  if (!results) return <div className={`rounded-md border border-dashed p-5 text-center ${bgClass}`}><div className="mb-2 text-xl text-[#f39c12]">◇</div><p className={`text-xs ${textMuted}`}>Задайте окно ВКД — бэкенд сравнит варианты, а ML-контур добавит раннее предупреждение.</p></div>;

  const selectedStart = results.ai_summary?.recommended_start;
  const sourceEntries = Object.entries(results.source_status || {});
  const mlMetrics = results.ml.test || results.windows.find((window) => window.ml_forecast)?.ml_forecast?.metrics || {};
  const requested = results.windows[0];
  const recommended = results.windows.find((window) => window.start === selectedStart)
    || results.windows.find((window) => window.on_pareto_front && window.start !== requested?.start)
    || results.windows[1];
  const comparisonWindows = [requested, recommended].filter((window, index, all) => (
    window && all.findIndex((item) => item.start === window.start) === index
  ));
  const activeWindow = results.windows.find((window) => window.start === selectedWindowStart) || requested;
  const saveResults = () => {
    const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `eva-risk-${results.request.start.slice(0, 16).replaceAll(':', '-')}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className={`flex w-full shrink-0 flex-col rounded-md border ${bgClass} ${isDarkTheme ? 'text-slate-300' : 'text-gray-700'}`}>
      <div className={`flex items-center justify-between rounded-t-md border-b p-4 ${headerBg}`}>
        <div><h2 className={`text-sm font-bold tracking-wide ${textMain}`}>Сводка оценки ВКД</h2><p className={`mt-0.5 text-[9px] ${textMuted}`}>{results.algo_version} · {results.windows.length} окон</p></div>
        <button type="button" onClick={saveResults} className="rounded-full border border-[#f39c12]/40 bg-[#f39c12]/10 px-3 py-1 text-[8px] font-bold uppercase text-[#f39c12] hover:bg-[#f39c12]/20">Сохранить JSON</button>
      </div>
      <div className="flex flex-col gap-4 p-4">
        <div className={`rounded-md border p-3 ${results.ai_summary?.status === 'ml-assisted' ? 'border-violet-400/40 bg-violet-400/10' : 'border-cyan-400/30 bg-cyan-400/5'}`}><div className="mb-1 flex items-center gap-2"><span className="text-base">✶</span><h3 className="text-[10px] font-black uppercase tracking-[0.14em] text-violet-300">{results.ai_summary?.title}</h3></div><p className="text-[10px] leading-relaxed">{results.ai_summary?.text}</p></div>
        <div className="grid grid-cols-2 gap-3">{comparisonWindows.map((window, index) => <WindowCard key={window.start} window={window} label={index === 0 ? 'Ваше окно' : 'Рекомендуемое'} selected={window.start === selectedWindowStart} onSelect={() => onSelectWindow(window.start)} headerBg={headerBg} textMuted={textMuted} />)}</div>
        {activeWindow && <div className={`rounded-md border p-3 ${headerBg}`}><div className="mb-2 flex items-center justify-between"><h3 className={`text-[10px] font-bold uppercase ${textMain}`}>Шкала воздействий</h3><span className={`text-[9px] ${textMuted}`}>{formatUtc(activeWindow.start)}–{formatUtc(new Date(new Date(activeWindow.start).getTime() + activeWindow.duration_h * 3600_000))} UTC</span></div><div className="relative h-2 overflow-hidden rounded-full bg-emerald-400/25"><div className="absolute inset-y-0 left-0 bg-amber-400" style={{ width: `${Math.min(100, (activeWindow.saa_minutes / (activeWindow.duration_h * 60)) * 100)}%` }} /><div className="absolute inset-y-0 right-0 bg-violet-400/70" style={{ width: `${Math.min(100, activeWindow.weather_combined * 100)}%` }} /></div><div className={`mt-2 flex justify-between text-[8px] ${textMuted}`}><span>ЮАА: {Math.round(activeWindow.saa_minutes)} мин</span><span>погодный индекс: {percent(activeWindow.weather_combined)}</span></div></div>}
        {results.orbit && <div className={`rounded-md border p-3 ${headerBg}`}><h3 className={`mb-1 text-[10px] font-bold uppercase ${textMain}`}>Маршрут МКС</h3><p className={`text-[9px] leading-relaxed ${textMuted}`}>{results.orbit.track.length} расчётных точек с шагом {results.orbit.step_s / 60} мин · SGP4 · {results.orbit.source.label}. Нажмите окно выше, чтобы подсветить его участок на глобусе.</p></div>}
        <div className={`rounded-md border p-3 ${headerBg}`}><h3 className={`mb-1 text-[10px] font-bold uppercase ${textMain}`}>Вывод физического контура</h3><p className="text-[10px] leading-relaxed">{results.verdict}: {results.reason}</p></div>
        {isProMode && <div className="grid grid-cols-2 gap-3"><div className={`rounded-md border border-dashed p-3 ${headerBg}`}><h3 className={`mb-2 text-[9px] font-bold uppercase ${textMain}`}>ML и ограничения</h3><p className={`text-[9px] leading-relaxed ${textMuted}`}>{results.ml.model}<br />Recall {percent(mlMetrics.recall)} · Precision {percent(mlMetrics.precision)}<br />{results.request.mode === 'current' ? 'Live: GOES + Kp + SGP4. Координаты — прогноз по TLE, не навигационная телеметрия.' : 'Исторический replay ограничен маем–июнем 2024; орбита восстановлена по TLE эпохи.'}</p></div><div className={`rounded-md border border-dashed p-3 ${headerBg}`}><h3 className={`mb-2 text-[9px] font-bold uppercase ${textMain}`}>Источники</h3>{sourceEntries.map(([name, status]) => <div key={name} className={`flex justify-between gap-2 text-[8px] ${textMuted}`}><span className="truncate">{name}</span><span>{status}</span></div>)}</div></div>}
      </div>
    </div>
  );
}
