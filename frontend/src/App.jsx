import { useEffect, useState } from 'react';
import ControlPanel from './components/ControlPanel';
import ResultsDashboard from './components/ResultsDashboard';
import CesiumMap from './components/CesiumMap';

export default function App() {
  const [params, setParams] = useState(() => {
    const defaultStart = new Date(Date.now() + 15 * 60 * 1000);
    return {
      mode: 'current',
      startDate: defaultStart.toISOString().slice(0, 10),
      startTime: defaultStart.toISOString().slice(11, 16),
      durationHours: 4,
      searchWindowHours: 24,
      filters: {
        weather: { S: true, G: true, R: true },
        collision: { micro: true, debris: true }
      }
    };
  });
  
  const [results, setResults] = useState(null);
  const [isProMode, setIsProMode] = useState(false);
  const [isDarkTheme, setIsDarkTheme] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveOrbit, setLiveOrbit] = useState(null);
  const [selectedWindowStart, setSelectedWindowStart] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    let active = true;
    const refreshStatus = async () => {
      try {
        const [statusResponse, orbitResponse] = await Promise.all([
          fetch('/api/live/status'),
          fetch('/api/orbit?hours=6&step_s=120&mode=current'),
        ]);
        if (statusResponse.ok && active) setLiveStatus(await statusResponse.json());
        if (orbitResponse.ok && active) setLiveOrbit(await orbitResponse.json());
      } catch {
        if (active) setLiveStatus(null);
      }
    };
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const handleCalculate = async () => {
    setIsLoading(true);
    setRequestError('');
    try {
      const start = new Date(`${params.startDate}T${params.startTime}:00Z`);
      const response = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start: start.toISOString(),
          duration_h: Number(params.durationHours),
          search_h: Number(params.searchWindowHours),
          step_min: 30,
          mode: params.mode,
          filters: params.filters,
        }),
      });

      if (!response.ok) {
        const details = await response.text();
        throw new Error(details || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setResults(data);
      setSelectedWindowStart(data.ai_summary?.recommended_start || data.windows?.[0]?.start || null);

    } catch (error) {
      console.error(error);
      setRequestError('Бэкенд не ответил. Проверьте, что API запущен на порту 8000.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setRequestError('');
    try {
      const response = await fetch('/api/live/refresh', { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setLiveStatus(await response.json());
      const orbitResponse = await fetch('/api/orbit?hours=6&step_s=120&mode=current');
      if (orbitResponse.ok) setLiveOrbit(await orbitResponse.json());
    } catch (error) {
      console.error(error);
      setRequestError('Не удалось принудительно обновить источники. Сохранён последний доступный срез.');
    } finally {
      setIsRefreshing(false);
    }
  };

  const mapOrbit = results?.orbit || liveOrbit;
  const selectedWindow = results?.windows?.find((item) => item.start === selectedWindowStart)
    || results?.windows?.[0];

  return (
    <div className={`flex h-screen w-screen overflow-hidden font-sans transition-colors ${isDarkTheme ? 'bg-[#1d1f27] text-slate-300' : 'bg-gray-100 text-gray-800'}`}>
      <div className={`w-[min(470px,43vw)] h-full border-r flex flex-col shrink-0 z-10 shadow-2xl ${isDarkTheme ? 'border-[#30333b] bg-[#1d1f27]' : 'border-gray-300 bg-white'}`}>
        <div className={`flex items-center justify-between p-4 border-b shrink-0 ${isDarkTheme ? 'border-[#30333b] bg-[#1b1d22]' : 'border-gray-200 bg-gray-50'}`}>
          <div className="flex items-center gap-3">
            <div>
              <div className="text-[#f39c12] font-black text-2xl tracking-tighter">AD ASTRA</div>
              <div className="text-[8px] uppercase tracking-[0.22em] text-[#8b91a0]">EVA risk intelligence</div>
              <div className="mt-1 flex items-center gap-1.5 text-[7px] uppercase tracking-wider text-emerald-400">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
                {liveStatus ? `live · ${new Date(liveStatus.generated_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC` : 'live · connecting'}
              </div>
            </div>
          </div>
          
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <span className="text-[9px] uppercase font-bold text-[#8b91a0]">Тема</span>
              <div className={`w-8 h-4 rounded-full relative transition-colors ${isDarkTheme ? 'bg-[#f39c12]' : 'bg-gray-400'}`} onClick={() => setIsDarkTheme(!isDarkTheme)}>
                <div className={`w-3 h-3 bg-white rounded-full absolute top-0.5 transition-transform ${isDarkTheme ? 'left-4' : 'left-0.5'}`} />
              </div>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <span className="text-[9px] uppercase font-bold text-[#8b91a0]">PRO</span>
              <div className={`w-8 h-4 rounded-full relative transition-colors ${isProMode ? 'bg-[#f39c12]' : 'bg-gray-400'}`} onClick={() => setIsProMode(!isProMode)}>
                <div className={`w-3 h-3 bg-white rounded-full absolute top-0.5 transition-transform ${isProMode ? 'left-4' : 'left-0.5'}`} />
              </div>
            </label>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
          <ControlPanel params={params} setParams={setParams} onCalculate={handleCalculate} onRefresh={handleRefresh} isRefreshing={isRefreshing} isProMode={isProMode} isDarkTheme={isDarkTheme} />
          {requestError && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">{requestError}</div>
          )}
          <ResultsDashboard results={results} params={params} isLoading={isLoading} isProMode={isProMode} isDarkTheme={isDarkTheme} selectedWindowStart={selectedWindowStart} onSelectWindow={setSelectedWindowStart} />
        </div>
      </div>

      <div className="flex-1 relative h-full bg-black">
        <CesiumMap key={`${mapOrbit?.start || 'loading'}-${mapOrbit?.source?.epoch || ''}`} orbit={mapOrbit} selectedWindow={selectedWindow} />
      </div>
    </div>
  );
}
