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

function WindowCard({ window, index, selected, headerBg, textMuted }) {
  const ml = window.ml_forecast;
  const risk = ml?.alert || window.weather_combined > 0.55;
  return (
    <div className={`rounded-md border p-3 transition-colors ${selected ? 'border-[#f39c12]/70 bg-[#f39c12]/8' : headerBg}`}>
      <div className="mb-2 flex items-start justify-between gap-3 border-b border-gray-500/20 pb-2">
        <div>
          <span className="text-[9px] font-bold uppercase tracking-wider">{index === 0 ? 'Ваше окно' : `Альтернатива ${index}`}</span>
          {window.on_pareto_front && <span className="ml-2 text-[8px] uppercase text-cyan-400">Парето</span>}
        </div>
        <span className={`text-[9px] font-bold uppercase ${risk ? 'text-orange-400' : 'text-emerald-400'}`}>{risk ? 'внимание' : 'норма'}</span>
      </div>
      <p className="font-mono text-xs font-semibold">{formatUtc(window.start)} UTC · {window.duration_h} ч</p>
      <div className={`mt-3 grid grid-cols-3 gap-2 text-[9px] ${textMuted}`}>
        <div><span className="block text-[8px] uppercase">Доза-прокси</span><b>{window.dose_usv_proxy} мкЗв</b></div>
        <div><span className="block text-[8px] uppercase">Kp max</span><b>{window.kp_max.toFixed(1)}</b></div>
        <div><span className="block text-[8px] uppercase">Данные</span><b>{percent(window.completeness)}</b></div>
      </div>
      {ml && <div className="mt-3 rounded-sm border border-violet-400/20 bg-violet-400/5 p-2"><div className="flex justify-between text-[9px]"><span>CatBoost · Q99 / 6ч</span><b>{percent(ml.probability)}</b></div><RiskBar value={ml.probability} threshold={ml.threshold} /></div>}
    </div>
  );
}

export default function ResultsDashboard({ results, isLoading, isProMode, isDarkTheme }) {
  const bgClass = isDarkTheme ? 'bg-[#24262d] border-[#30333b]' : 'bg-white border-gray-200';
  const headerBg = isDarkTheme ? 'bg-[#1b1d22] border-[#30333b]' : 'bg-gray-100 border-gray-200';
  const textMain = isDarkTheme ? 'text-white' : 'text-gray-900';
  const textMuted = isDarkTheme ? 'text-[#8b91a0]' : 'text-gray-500';

  if (isLoading) return <div className={`flex w-full shrink-0 animate-pulse flex-col gap-4 rounded-md border p-6 ${bgClass}`}><div className="h-4 w-1/3 rounded bg-gray-500/20" /><div className="h-32 w-full rounded bg-gray-500/10" /></div>;
  if (!results) return <div className={`rounded-md border border-dashed p-5 text-center ${bgClass}`}><div className="mb-2 text-xl text-[#f39c12]">◇</div><p className={`text-xs ${textMuted}`}>Задайте окно ВКД — бэкенд сравнит варианты, а ML-контур добавит раннее предупреждение.</p></div>;

  const selectedStart = results.ai_summary?.recommended_start;
  const sourceEntries = Object.entries(results.source_status || {});
  return (
    <div className={`flex w-full shrink-0 flex-col rounded-md border ${bgClass} ${isDarkTheme ? 'text-slate-300' : 'text-gray-700'}`}>
      <div className={`flex items-center justify-between rounded-t-md border-b p-4 ${headerBg}`}>
        <div><h2 className={`text-sm font-bold tracking-wide ${textMain}`}>Сводка оценки ВКД</h2><p className={`mt-0.5 text-[9px] ${textMuted}`}>{results.algo_version} · {results.windows.length} окон</p></div>
        <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-[8px] font-bold uppercase text-emerald-400">API online</span>
      </div>
      <div className="flex flex-col gap-4 p-4">
        <div className={`rounded-md border p-3 ${results.ai_summary?.status === 'ml-assisted' ? 'border-violet-400/40 bg-violet-400/10' : 'border-cyan-400/30 bg-cyan-400/5'}`}><div className="mb-1 flex items-center gap-2"><span className="text-base">✶</span><h3 className="text-[10px] font-black uppercase tracking-[0.14em] text-violet-300">{results.ai_summary?.title}</h3></div><p className="text-[10px] leading-relaxed">{results.ai_summary?.text}</p></div>
        <div className="grid grid-cols-2 gap-3">{results.windows.slice(0, 6).map((window, index) => <WindowCard key={window.start} window={window} index={index} selected={window.start === selectedStart} headerBg={headerBg} textMuted={textMuted} />)}</div>
        <div className={`rounded-md border p-3 ${headerBg}`}><h3 className={`mb-1 text-[10px] font-bold uppercase ${textMain}`}>Вывод физического контура</h3><p className="text-[10px] leading-relaxed">{results.verdict}: {results.reason}</p></div>
        {isProMode && <div className="grid grid-cols-2 gap-3"><div className={`rounded-md border border-dashed p-3 ${headerBg}`}><h3 className={`mb-2 text-[9px] font-bold uppercase ${textMain}`}>ML-паспорт</h3><p className={`text-[9px] leading-relaxed ${textMuted}`}>{results.ml.model}<br />Recall 85.64% · Precision 70.28%<br />Исторический holdout, не допуск к ВКД.</p></div><div className={`rounded-md border border-dashed p-3 ${headerBg}`}><h3 className={`mb-2 text-[9px] font-bold uppercase ${textMain}`}>Источники</h3>{sourceEntries.map(([name, status]) => <div key={name} className={`flex justify-between gap-2 text-[8px] ${textMuted}`}><span className="truncate">{name}</span><span>{status}</span></div>)}</div></div>}
      </div>
    </div>
  );
}
