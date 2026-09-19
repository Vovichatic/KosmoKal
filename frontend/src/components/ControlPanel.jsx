import { useState } from 'react';

export default function ControlPanel({ params, setParams, onCalculate, onRefresh, isRefreshing, isProMode, isDarkTheme }) {
  const [showSources, setShowSources] = useState(false);
  const [error, setError] = useState(null);
  const [sourcesEnabled, setSourcesEnabled] = useState({ swpc: true, celestrak: true });

  // Ограничения для исторического режима (датасет хакатона)
  const MIN_HISTORICAL = '2024-05-01';
  const MAX_HISTORICAL = '2024-06-30';

  // Ограничения для Live-режима (сегодня и завтра)
  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);
  const tomorrowStr = new Date(today.getTime() + 24 * 3600_000).toISOString().slice(0, 10);

  const isHistorical = params.mode === 'historical';

  const handleChange = (e) => {
    setError(null);
    if (e.target.name === 'mode') {
      // При смене режима подставляем соответствующую валидную дату
      const defaultDate = e.target.value === 'historical' ? MIN_HISTORICAL : todayStr;
      setParams({ ...params, mode: e.target.value, startDate: defaultDate, startTime: '' });
      return;
    }
    setParams({ ...params, [e.target.name]: e.target.value });
  };
  
  const toggleFilter = (category, type) => {
    setParams(prev => ({
      ...prev,
      filters: { ...prev.filters, [category]: { ...prev.filters[category], [type]: !prev.filters[category][type] } }
    }));
  };

  const toggleSourceGroup = async (group) => {
    const nextEnabled = !sourcesEnabled[group];
    const ids = group === 'swpc'
      ? ['swpc.goes.protons', 'swpc.kp', 'swpc.alerts']
      : ['celestrak.gp.iss'];
    setSourcesEnabled((current) => ({ ...current, [group]: nextEnabled }));
    try {
      await Promise.all(ids.map((id) => fetch(`/api/sources/${id}/${nextEnabled ? 'enable' : 'disable'}`, { method: 'POST' })));
    } catch {
      setSourcesEnabled((current) => ({ ...current, [group]: !nextEnabled }));
      setError('Не удалось изменить состояние источника');
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError(null);
    
    if (!params.startDate || !params.startTime) {
      setError("Укажите дату и точное время ВКД");
      return;
    }

    if (isHistorical) {
      if (params.startDate < MIN_HISTORICAL || params.startDate > MAX_HISTORICAL) {
        setError("Ошибка: Дата должна быть в диапазоне от 01.05.2024 до 30.06.2024");
        return;
      }
    } else {
      const selectedTime = new Date(`${params.startDate}T${params.startTime}:00Z`).getTime();
      const nowTime = new Date().getTime();
      
      if (selectedTime < nowTime - 120000) {
        setError("Ошибка: Время старта уже прошло");
        return;
      }
      if (selectedTime > nowTime + 24 * 3600000) {
        setError("Ошибка: Прогноз возможен максимум на 24 часа вперед");
        return;
      }
    }

    onCalculate();
  };

  const bgClass = isDarkTheme ? 'bg-[#24262d] border-[#30333b]' : 'bg-white border-gray-200';
  const inputBg = isDarkTheme ? 'bg-[#1b1d22] border-[#30333b] text-gray-200' : 'bg-gray-50 border-gray-300 text-gray-800';
  const textMuted = isDarkTheme ? 'text-[#8b91a0]' : 'text-gray-500';

  return (
    <form onSubmit={handleSubmit} className={`border p-5 rounded-md shrink-0 w-full ${bgClass}`}>
      <div className="flex flex-col gap-4 mb-4">
        <div>
          <label className={`text-[10px] font-semibold uppercase tracking-wider block mb-1 ${textMuted}`}>Режим данных</label>
          <select name="mode" value={params.mode} onChange={handleChange} className={`w-full p-2 rounded-sm text-sm outline-none border focus:border-[#f39c12] ${inputBg}`}>
            <option value="current">Текущая обстановка (Live)</option>
            <option value="historical">Историческая дата</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
             <label className={`text-[10px] font-semibold uppercase tracking-wider block mb-1 ${textMuted}`}>Дата (UTC)</label>
             <input 
               type="date" 
               name="startDate" 
               value={params.startDate} 
               onChange={handleChange}
               min={isHistorical ? MIN_HISTORICAL : todayStr}
               max={isHistorical ? MAX_HISTORICAL : tomorrowStr}
               required
               className={`w-full p-2 rounded-sm text-sm outline-none border focus:border-[#f39c12] ${inputBg}`} 
             />
          </div>
          <div>
             <label className={`text-[10px] font-semibold uppercase tracking-wider block mb-1 ${textMuted}`}>Время (UTC)</label>
             <input type="time" 
               name="startTime" 
               value={params.startTime} 
               onChange={handleChange}
               required
               className={`w-full p-2 rounded-sm text-sm outline-none border focus:border-[#f39c12] ${inputBg}`} 
             />
          </div>
          <div>
             <label className={`text-[10px] font-semibold uppercase tracking-wider block mb-1 ${textMuted}`}>Длительность (Ч)</label>
             <input type="number" min="1" max="8" name="durationHours" value={params.durationHours} onChange={handleChange} required className={`w-full p-2 rounded-sm text-sm outline-none border focus:border-[#f39c12] ${inputBg}`} />
          </div>
          <div>
             <label className={`text-[10px] font-semibold uppercase tracking-wider block mb-1 ${textMuted}`}>Период поиска (Ч)</label>
             <input type="number" min="1" max="24" name="searchWindowHours" value={params.searchWindowHours} onChange={handleChange} required className={`w-full p-2 rounded-sm text-sm outline-none border focus:border-[#f39c12] ${inputBg}`} />
          </div>
        </div>
      </div>

      <div className={`p-3 border rounded-sm mb-4 ${isDarkTheme ? 'bg-[#1b1d22] border-[#30333b]' : 'bg-gray-50 border-gray-200'}`}>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className={`text-[10px] font-bold uppercase mb-2 ${isDarkTheme ? 'text-white' : 'text-black'}`}>Космическая погода</h4>
            <div className="flex gap-3">
              {['S', 'G', 'R'].map(type => (
                <label key={type} className="flex items-center gap-1 cursor-pointer">
                  <input type="checkbox" checked={params.filters.weather[type]} onChange={() => toggleFilter('weather', type)} className="accent-[#f39c12]" />
                  <span className={`text-xs ${textMuted}`}>{type}</span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <h4 className={`text-[10px] font-bold uppercase mb-2 ${isDarkTheme ? 'text-white' : 'text-black'}`}>Столкновение</h4>
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={params.filters.collision.micro} onChange={() => toggleFilter('collision', 'micro')} className="accent-[#f39c12]" />
                <span className={`text-xs ${textMuted}`}>Микрометеориты</span>
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={params.filters.collision.debris} onChange={() => toggleFilter('collision', 'debris')} className="accent-[#f39c12]" />
                <span className={`text-xs ${textMuted}`}>Косм. мусор</span>
              </label>
            </div>
          </div>
        </div>
      </div>

      {isProMode && (
        <div className="flex gap-2 mb-4">
          <button type="button" onClick={() => setShowSources(!showSources)} className={`flex-1 p-2 border rounded-sm text-xs font-semibold uppercase tracking-wider transition-colors ${isDarkTheme ? 'bg-[#1b1d22] border-[#30333b] text-gray-300 hover:bg-[#30333b]' : 'bg-gray-100 border-gray-300 text-gray-700 hover:bg-gray-200'}`}>
            {showSources ? 'Скрыть источники' : 'Настройка источников'}
          </button>
          <button type="button" onClick={onRefresh} disabled={isRefreshing} className="px-4 bg-[#27ae60] hover:bg-[#2ecc71] disabled:cursor-wait disabled:opacity-60 text-white rounded-sm text-xs font-bold uppercase tracking-wider flex items-center justify-center">
            {isRefreshing ? 'Обновление…' : 'Обновить'}
          </button>
        </div>
      )}

      {isProMode && showSources && (
        <div className={`p-3 border rounded-sm mb-4 text-xs flex flex-col gap-2 ${isDarkTheme ? 'bg-[#1b1d22] border-[#30333b] text-gray-300' : 'bg-gray-50 border-gray-200 text-gray-700'}`}>
          <label className="flex items-center justify-between cursor-pointer border-b border-dashed pb-1 border-gray-500">
            <span>NOAA Space Weather Prediction Center</span> <input type="checkbox" checked={sourcesEnabled.swpc} onChange={() => toggleSourceGroup('swpc')} className="accent-[#f39c12]" />
          </label>
          <label className="flex items-center justify-between cursor-pointer">
            <span>CelesTrak (орбита МКС)</span> <input type="checkbox" checked={sourcesEnabled.celestrak} onChange={() => toggleSourceGroup('celestrak')} className="accent-[#f39c12]" />
          </label>
        </div>
      )}

      {error && (
        <div className="mb-3 p-2 bg-red-500/20 border border-red-500/50 rounded-sm text-red-500 text-[10px] uppercase font-bold text-center tracking-wider">
          {error}
        </div>
      )}

      <button type="submit" className="w-full bg-[#f39c12] hover:bg-[#e67e22] text-[#1b1d22] font-bold py-2.5 px-4 rounded-sm transition-colors text-xs tracking-wider uppercase">
        Рассчитать риски
      </button>
    </form>
  );
}
