import { useState } from 'react';
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
        }),
      });

      if (!response.ok) {
        const details = await response.text();
        throw new Error(details || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setResults(data); 

    } catch (error) {
      console.error(error);
      setRequestError('Бэкенд не ответил. Проверьте, что API запущен на порту 8000.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={`flex h-screen w-screen overflow-hidden font-sans transition-colors ${isDarkTheme ? 'bg-[#1d1f27] text-slate-300' : 'bg-gray-100 text-gray-800'}`}>
      <div className={`w-[550px] h-full border-r flex flex-col shrink-0 z-10 shadow-2xl ${isDarkTheme ? 'border-[#30333b] bg-[#1d1f27]' : 'border-gray-300 bg-white'}`}>
        <div className={`flex items-center justify-between p-4 border-b shrink-0 ${isDarkTheme ? 'border-[#30333b] bg-[#1b1d22]' : 'border-gray-200 bg-gray-50'}`}>
          <div className="flex items-center gap-3">
            <div>
              <div className="text-[#f39c12] font-black text-2xl tracking-tighter">AD ASTRA</div>
              <div className="text-[8px] uppercase tracking-[0.22em] text-[#8b91a0]">EVA risk intelligence</div>
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
          <ControlPanel params={params} setParams={setParams} onCalculate={handleCalculate} isProMode={isProMode} isDarkTheme={isDarkTheme} />
          {requestError && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">{requestError}</div>
          )}
          <ResultsDashboard results={results} params={params} isLoading={isLoading} isProMode={isProMode} isDarkTheme={isDarkTheme} />
        </div>
      </div>

      <div className="flex-1 relative h-full bg-black">
        <CesiumMap trajectory={results?.windows || []} />
      </div>
    </div>
  );
}
