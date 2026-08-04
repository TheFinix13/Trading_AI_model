//+------------------------------------------------------------------+
//| ExportCalendarHistory.mq5                                        |
//| Phase AI (Sae v2 S1): dump the MetaQuotes economic calendar      |
//| history for USD events to MQL5/Files/calendar_history_usd.csv.  |
//| Run once on any chart; requires terminal calendar sync (online). |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input datetime InpFrom = D'2015.01.01 00:00';
input string   InpCurrency = "USD";
input string   InpOutFile = "calendar_history_usd.csv";

void OnStart()
  {
   MqlCalendarValue values[];
   datetime to = TimeCurrent();
   if(!CalendarValueHistory(values, InpFrom, to, NULL, InpCurrency))
     {
      PrintFormat("CalendarValueHistory failed: %d", GetLastError());
      return;
     }
   int h = FileOpen(InpOutFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("FileOpen failed: %d", GetLastError());
      return;
     }
   FileWrite(h, "time_utc", "event_id", "event_name", "importance",
             "actual", "forecast", "previous", "revised", "unit_digits");
   int written = 0;
   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      // Keep High importance only -- matches the frozen panel's scope.
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH)
         continue;
      // MqlCalendarValue raw fields are value*10^6 with LONG_MIN as
      // "not set"; use the accessor helpers for clean doubles.
      double act = values[i].HasActualValue()   ? values[i].GetActualValue()   : EMPTY_VALUE;
      double fc  = values[i].HasForecastValue() ? values[i].GetForecastValue() : EMPTY_VALUE;
      double prv = values[i].HasPreviousValue() ? values[i].GetPreviousValue() : EMPTY_VALUE;
      double rev = values[i].HasRevisedValue()  ? values[i].GetRevisedValue()  : EMPTY_VALUE;
      FileWrite(h,
                TimeToString(values[i].time, TIME_DATE | TIME_MINUTES),
                (long)values[i].event_id,
                ev.name,
                (int)ev.importance,
                DoubleToString(act, 6),
                DoubleToString(fc, 6),
                DoubleToString(prv, 6),
                DoubleToString(rev, 6),
                (int)ev.digits);
      written++;
     }
   FileClose(h);
   PrintFormat("wrote %d high-impact %s rows to MQL5/Files/%s",
               written, InpCurrency, InpOutFile);
  }
//+------------------------------------------------------------------+
