//+------------------------------------------------------------------+
//| ExportCalendarHistory.mq5                                        |
//| Phase AI (Sae v2 S1): dump the MetaQuotes economic calendar      |
//| history for USD events to MQL5/Files/calendar_history_usd.csv.  |
//| Run once on any chart; requires terminal calendar sync (online). |
//| If it reports 0 raw values: open the Toolbox "Calendar" tab      |
//| first so the terminal downloads the calendar DB, wait ~1 min,    |
//| then re-run.                                                     |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input datetime InpFrom = D'2015.01.01 00:00';
input string   InpCurrency = "USD";
input string   InpOutFile = "calendar_history_usd.csv";

void OnStart()
  {
   // Diagnostic 0: is the calendar DB alive at all? Query ALL
   // currencies over the last 30 days before the big pull.
   MqlCalendarValue probe[];
   datetime now = TimeCurrent();
   bool probe_ok = CalendarValueHistory(probe, now - 30 * 86400, now, NULL, NULL);
   PrintFormat("calendar probe (all currencies, last 30 days): ok=%s n=%d err=%d",
               probe_ok ? "true" : "false", ArraySize(probe), GetLastError());
   if(!probe_ok || ArraySize(probe) == 0)
     {
      Print("Calendar DB looks EMPTY/disabled. Fix: 1) Toolbox -> Calendar tab, "
            "let it populate; 2) Tools -> Options -> Server: 'Enable news' ticked; "
            "3) stay online ~1 min; 4) re-run this script.");
      // continue anyway -- the full-range query sometimes triggers the sync
     }

   MqlCalendarValue values[];
   ResetLastError();
   if(!CalendarValueHistory(values, InpFrom, now, NULL, InpCurrency))
     {
      PrintFormat("CalendarValueHistory failed: %d", GetLastError());
      return;
     }
   PrintFormat("raw %s values returned: %d (from %s)", InpCurrency,
               ArraySize(values), TimeToString(InpFrom, TIME_DATE));

   int h = FileOpen(InpOutFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("FileOpen failed: %d", GetLastError());
      return;
     }
   FileWrite(h, "time_utc", "event_id", "event_name", "importance",
             "actual", "forecast", "previous", "revised", "unit_digits");
   int written = 0;
   int n_high = 0, n_med = 0, n_low = 0, n_none = 0;
   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      if(ev.importance == CALENDAR_IMPORTANCE_HIGH) n_high++;
      else if(ev.importance == CALENDAR_IMPORTANCE_MODERATE) n_med++;
      else if(ev.importance == CALENDAR_IMPORTANCE_LOW) n_low++;
      else n_none++;
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
   PrintFormat("importance split: high=%d moderate=%d low=%d none=%d",
               n_high, n_med, n_low, n_none);
   PrintFormat("wrote %d high-impact %s rows to MQL5/Files/%s",
               written, InpCurrency, InpOutFile);
  }
//+------------------------------------------------------------------+
