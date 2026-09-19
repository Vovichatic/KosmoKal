import React from 'react';

export default function ResultsDashboard({ results, params, isLoading, isProMode, isDarkTheme }) {
  const bgClass = isDarkTheme ? 'bg-[#24262d] border-[#30333b]' : 'bg-white border-gray-200';
  const headerBg = isDarkTheme ? 'bg-[#1b1d22] border-[#30333b]' : 'bg-gray-100 border-gray-200';
  const textMain = isDarkTheme ? 'text-white' : 'text-gray-900';
  const textMuted = isDarkTheme ? 'text-[#8b91a0]' : 'text-gray-500';

  if (isLoading) {
    return (
      <div className={`border rounded-md p-6 w-full shrink-0 flex flex-col gap-4 animate-pulse ${bgClass}`}>
        <div className="h-4 bg-gray-500/20 rounded w-1/3"></div>
        <div className="h-32 bg-gray-500/10 rounded w-full"></div>
      </div>
    );
  }

  if (!results) return null;

  const startObj = (params.startDate && params.startTime) 
    ? new Date(`${params.startDate}T${params.startTime}`) 
    : new Date();
    
  const duration = parseInt(params.durationHours) || 4;
  const endObj = new Date(startObj.getTime() + duration * 3600000);
  
  const formatTime = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const userTimeStr = `${formatTime(startObj)} - ${formatTime(endObj)}`;

  const algStart = new Date(startObj.getTime() + 5 * 3600000);
  const algEnd = new Date(algStart.getTime() + duration * 3600000);
  const algTimeStr = `${formatTime(algStart)} - ${formatTime(algEnd)}`;

  return (
    <div className={`border rounded-md flex flex-col w-full shrink-0 ${bgClass} ${isDarkTheme ? 'text-slate-300' : 'text-gray-700'}`}>
      <div className={`p-4 border-b flex justify-between items-center rounded-t-md ${headerBg}`}>
        <h2 className={`text-sm font-bold tracking-wide ${textMain}`}>Сводка оценки ВКД</h2>
      </div>
      
      <div className="p-4 flex flex-col gap-6">
        <div className="border border-[#27ae60]/50 bg-[#27ae60]/10 p-3 rounded-sm">
          <h3 className="font-bold text-[#27ae60] text-[11px] uppercase tracking-wider mb-1">Рекомендация ГОГУ</h3>
          <p className="text-xs leading-relaxed">Система рекомендует <b>Окно №2</b>. Пользовательское Окно №1 попадает в зону риска сближения с космическим мусором на восходящем витке.</p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className={`p-3 border rounded-sm ${headerBg}`}>
            <div className="flex justify-between items-center mb-2 border-b border-gray-500/30 pb-2">
              <span className={`text-[10px] uppercase font-bold ${textMuted}`}>Окно №1 (Ваш запрос)</span>
              <span className="text-red-500 text-[10px] font-bold">Риск</span>
            </div>
            
            <p className="text-xs mb-2 font-mono"><b>{userTimeStr} UTC</b> ({duration} ч)</p>
            <p className={`text-[10px] mb-4 ${textMuted}`}>Траектория: Витки 4521-4523, теневая фаза 30%</p>
            
            <div className="w-full h-10 border-l border-b border-gray-500/30 relative mb-4">
              <div className="absolute left-[10%] w-[30%] top-1 h-2 bg-red-500 rounded-sm"></div>
              <div className="absolute left-[60%] w-[20%] top-5 h-2 bg-yellow-500 rounded-sm"></div>
            </div>

            <div>
              <div className="relative group bg-red-500/10 border-l-2 border-red-500 p-2 mb-2 cursor-help">
                <span className="text-red-500 text-[10px] font-bold">Мусор (ID 41332)</span>
                
                {isProMode && (
                  <div className={`absolute bottom-full left-0 mb-2 w-64 p-3 border rounded shadow-xl z-50 hidden group-hover:block ${bgClass}`}>
                    <h4 className={`text-xs font-bold mb-1 ${textMain}`}>Сближение с объектом 41332</h4>
                    <ul className={`text-[10px] flex flex-col gap-1 ${textMuted}`}>
                      <li><b>Ожидаемый период:</b> {formatTime(new Date(startObj.getTime() + 900000))} - {formatTime(new Date(startObj.getTime() + 1320000))} UTC</li>
                      <li><b>Данные:</b> Дистанция 1.2 км</li>
                      <li><b>Уверенность:</b> Высокая (Погрешность 50м)</li>
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className={`p-3 border rounded-sm border-[#27ae60]/50 bg-[#27ae60]/5`}>
            <div className="flex justify-between items-center mb-2 border-b border-gray-500/30 pb-2">
              <span className={`text-[10px] uppercase font-bold text-[#27ae60]`}>Окно №2 (Алгоритм)</span>
              <span className="text-[#27ae60] text-[10px] font-bold">Норма</span>
            </div>
            
            <p className="text-xs mb-2 font-mono"><b>{algTimeStr} UTC</b> ({duration} ч)</p>
            <p className={`text-[10px] mb-4 ${textMuted}`}>Траектория: Витки 4524-4526, теневая фаза 45%</p>
            
            <div className="w-full h-10 border-l border-b border-gray-500/30 relative mb-4">
              <div className="absolute left-[30%] w-[10%] top-1 h-2 bg-emerald-500 rounded-sm"></div>
            </div>

            <div>
              <div className="bg-emerald-500/10 border-l-2 border-emerald-500 p-2 mb-2">
                <span className="text-emerald-500 text-[10px] font-bold">Показатели в норме</span>
              </div>
            </div>
          </div>
        </div>

        {isProMode && (
          <div className="grid grid-cols-2 gap-4 mt-2">
            <div className={`p-3 border border-dashed rounded-sm ${headerBg}`}>
              <h3 className={`text-[10px] uppercase font-bold mb-1 ${textMain}`}>Ограничения модели</h3>
              <p className={`text-[9px] ${textMuted}`}>Погрешность орбиты мусора возрастает на 15% за каждый час прогноза.</p>
            </div>
            <div className={`p-3 border border-dashed rounded-sm ${headerBg}`}>
              <h3 className={`text-[10px] uppercase font-bold mb-1 ${textMain}`}>Сводка источников</h3>
              <p className={`text-[9px] ${textMuted}`}>NOAA (Каждые 5 мин)
CelesTrak (Каждые 6 ч)</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}