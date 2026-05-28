//+------------------------------------------------------------------+
//| TradingPartner_Overlay.mq5                                        |
//| EURUSD AI Trading Agent - Chart Visualization                     |
//| Reads agent analysis and draws zones/levels/signals on chart      |
//+------------------------------------------------------------------+
#property copyright "Trading AI Model"
#property version   "1.00"
#property description "Visualizes AI agent analysis on chart"

#include <Trade\Trade.mqh>

input int    UpdateIntervalSeconds = 5;      // How often to check for new instructions
input string InstructionFile = "agent_drawings.json";  // File to read from
input bool   ShowZones = true;              // Show liquidity/SD zones
input bool   ShowLevels = true;             // Show structural levels
input bool   ShowFibs = true;              // Show fib levels
input bool   ShowBias = true;              // Show HTF bias indicator
input bool   ShowSignals = true;           // Show entry/exit signals
input color  LZIZoneColor = clrPurple;     // LZI zone color
input color  FVGZoneColor = clrDodgerBlue; // FVG zone color
input color  SDZoneColor = clrOrangeRed;   // SD zone color
input color  ResistanceColor = clrRed;     // Resistance level color
input color  SupportColor = clrLimeGreen;  // Support level color
input color  FibColor = clrGold;           // Fib level color
input color  BuySignalColor = clrLime;     // Buy signal color
input color  SellSignalColor = clrRed;     // Sell signal color

// Global variables
datetime lastFileModified = 0;
string PREFIX = "AI_";  // Prefix for all objects created by this EA

//+------------------------------------------------------------------+
int OnInit()
{
    EventSetTimer(UpdateIntervalSeconds);
    Print("TradingPartner Overlay initialized. Watching: ", InstructionFile);
    LoadAndDraw();
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    ObjectsDeleteAll(0, PREFIX);
    Print("TradingPartner Overlay removed. All drawings cleared.");
}

//+------------------------------------------------------------------+
void OnTimer()
{
    LoadAndDraw();
}

//+------------------------------------------------------------------+
void LoadAndDraw()
{
    if(!FileIsExist(InstructionFile))
        return;

    int handle = FileOpen(InstructionFile, FILE_READ|FILE_TXT|FILE_ANSI);
    if(handle == INVALID_HANDLE)
        return;

    string content = "";
    while(!FileIsEnding(handle))
        content += FileReadString(handle) + "\n";
    FileClose(handle);

    if(StringLen(content) < 10)
        return;

    ObjectsDeleteAll(0, PREFIX);

    ParseAndDraw(content);

    ChartRedraw();
}

//+------------------------------------------------------------------+
void ParseAndDraw(string json)
{
    if(ShowZones)
        DrawZones(json);

    if(ShowLevels)
        DrawLevels(json);

    if(ShowFibs)
        DrawFibs(json);

    if(ShowBias)
        DrawBias(json);

    if(ShowSignals)
        DrawSignals(json);
}

//+------------------------------------------------------------------+
void DrawZones(string json)
{
    int zonesStart = StringFind(json, "\"zones\"");
    if(zonesStart < 0) return;

    int arrStart = StringFind(json, "[", zonesStart);
    int arrEnd = FindMatchingBracket(json, arrStart);
    if(arrStart < 0 || arrEnd < 0) return;

    string zonesArr = StringSubstr(json, arrStart, arrEnd - arrStart + 1);

    int pos = 0;
    int idx = 0;
    while(true)
    {
        int objStart = StringFind(zonesArr, "{", pos);
        if(objStart < 0) break;
        int objEnd = StringFind(zonesArr, "}", objStart);
        if(objEnd < 0) break;

        string obj = StringSubstr(zonesArr, objStart, objEnd - objStart + 1);
        pos = objEnd + 1;

        string zoneType = ExtractString(obj, "type");
        double high = ExtractDouble(obj, "high");
        double low = ExtractDouble(obj, "low");
        string quality = ExtractString(obj, "quality");
        string status = ExtractString(obj, "status");
        string label = ExtractString(obj, "label");

        if(high <= 0 || low <= 0) continue;

        color zoneColor;
        if(zoneType == "LZI") zoneColor = LZIZoneColor;
        else if(zoneType == "FVG") zoneColor = FVGZoneColor;
        else zoneColor = SDZoneColor;

        if(status == "DEPLETED")
            zoneColor = clrGray;

        string name = PREFIX + "ZONE_" + IntegerToString(idx);
        datetime t1 = iTime(_Symbol, PERIOD_H1, 20);
        datetime t2 = TimeCurrent() + PeriodSeconds(PERIOD_H4);

        ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, high, t2, low);
        ObjectSetInteger(0, name, OBJPROP_COLOR, zoneColor);
        ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
        ObjectSetInteger(0, name, OBJPROP_FILL, true);
        ObjectSetInteger(0, name, OBJPROP_BACK, true);
        ObjectSetString(0, name, OBJPROP_TOOLTIP, label + " [" + quality + "] " + status);

        string labelName = PREFIX + "ZLBL_" + IntegerToString(idx);
        ObjectCreate(0, labelName, OBJ_TEXT, 0, t1, high);
        ObjectSetString(0, labelName, OBJPROP_TEXT, " " + label);
        ObjectSetInteger(0, labelName, OBJPROP_COLOR, zoneColor);
        ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);

        idx++;
    }
}

//+------------------------------------------------------------------+
void DrawLevels(string json)
{
    int levelsStart = StringFind(json, "\"levels\"");
    if(levelsStart < 0) return;

    int arrStart = StringFind(json, "[", levelsStart);
    int arrEnd = FindMatchingBracket(json, arrStart);
    if(arrStart < 0 || arrEnd < 0) return;

    string levelsArr = StringSubstr(json, arrStart, arrEnd - arrStart + 1);

    int pos = 0;
    int idx = 0;
    while(true)
    {
        int objStart = StringFind(levelsArr, "{", pos);
        if(objStart < 0) break;
        int objEnd = StringFind(levelsArr, "}", objStart);
        if(objEnd < 0) break;

        string obj = StringSubstr(levelsArr, objStart, objEnd - objStart + 1);
        pos = objEnd + 1;

        double price = ExtractDouble(obj, "price");
        string levelType = ExtractString(obj, "type");
        string timeframe = ExtractString(obj, "timeframe");
        string label = ExtractString(obj, "label");

        if(price <= 0) continue;

        color lineColor = (levelType == "resistance") ? ResistanceColor : SupportColor;
        ENUM_LINE_STYLE style = (timeframe == "D1") ? STYLE_SOLID : STYLE_DASH;
        int width = (timeframe == "D1") ? 2 : 1;

        string name = PREFIX + "LVL_" + IntegerToString(idx);
        ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
        ObjectSetInteger(0, name, OBJPROP_COLOR, lineColor);
        ObjectSetInteger(0, name, OBJPROP_STYLE, style);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
        ObjectSetString(0, name, OBJPROP_TOOLTIP, label + " (" + timeframe + ")");

        string lblName = PREFIX + "LLBL_" + IntegerToString(idx);
        ObjectCreate(0, lblName, OBJ_TEXT, 0, TimeCurrent(), price);
        ObjectSetString(0, lblName, OBJPROP_TEXT, " " + label + " " + timeframe);
        ObjectSetInteger(0, lblName, OBJPROP_COLOR, lineColor);
        ObjectSetInteger(0, lblName, OBJPROP_FONTSIZE, 8);

        idx++;
    }
}

//+------------------------------------------------------------------+
void DrawFibs(string json)
{
    int fibsStart = StringFind(json, "\"fibs\"");
    if(fibsStart < 0) return;

    int arrStart = StringFind(json, "[", fibsStart);
    int arrEnd = FindMatchingBracket(json, arrStart);
    if(arrStart < 0 || arrEnd < 0) return;

    string fibsArr = StringSubstr(json, arrStart, arrEnd - arrStart + 1);

    int pos = 0;
    int idx = 0;
    while(true)
    {
        int objStart = StringFind(fibsArr, "{", pos);
        if(objStart < 0) break;
        int objEnd = StringFind(fibsArr, "}", objStart);
        if(objEnd < 0) break;

        string obj = StringSubstr(fibsArr, objStart, objEnd - objStart + 1);
        pos = objEnd + 1;

        double price = ExtractDouble(obj, "price");
        string label = ExtractString(obj, "label");

        if(price <= 0) continue;

        string name = PREFIX + "FIB_" + IntegerToString(idx);
        ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
        ObjectSetInteger(0, name, OBJPROP_COLOR, FibColor);
        ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
        ObjectSetString(0, name, OBJPROP_TOOLTIP, label);

        idx++;
    }
}

//+------------------------------------------------------------------+
void DrawBias(string json)
{
    int biasStart = StringFind(json, "\"bias\"");
    if(biasStart < 0) return;

    string direction = ExtractStringAfter(json, "\"direction\"", biasStart);
    string confidence = ExtractStringAfter(json, "\"confidence\"", biasStart);
    string patterns = ExtractStringAfter(json, "\"patterns_summary\"", biasStart);

    string name = PREFIX + "BIAS_LABEL";
    ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
    ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 30);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 11);

    color biasColor = clrWhite;
    if(direction == "BEARISH") biasColor = clrOrangeRed;
    else if(direction == "BULLISH") biasColor = clrLimeGreen;

    ObjectSetInteger(0, name, OBJPROP_COLOR, biasColor);
    ObjectSetString(0, name, OBJPROP_TEXT, "AI Bias: " + direction + " (" + confidence + ")");

    string pname = PREFIX + "BIAS_PATTERNS";
    ObjectCreate(0, pname, OBJ_LABEL, 0, 0, 0);
    ObjectSetInteger(0, pname, OBJPROP_CORNER, CORNER_LEFT_UPPER);
    ObjectSetInteger(0, pname, OBJPROP_XDISTANCE, 10);
    ObjectSetInteger(0, pname, OBJPROP_YDISTANCE, 48);
    ObjectSetInteger(0, pname, OBJPROP_FONTSIZE, 9);
    ObjectSetInteger(0, pname, OBJPROP_COLOR, clrLightGray);
    ObjectSetString(0, pname, OBJPROP_TEXT, patterns);
}

//+------------------------------------------------------------------+
void DrawSignals(string json)
{
    int sigStart = StringFind(json, "\"signals\"");
    if(sigStart < 0) return;

    int arrStart = StringFind(json, "[", sigStart);
    int arrEnd = FindMatchingBracket(json, arrStart);
    if(arrStart < 0 || arrEnd < 0) return;

    string sigArr = StringSubstr(json, arrStart, arrEnd - arrStart + 1);

    int pos = 0;
    int idx = 0;
    while(true)
    {
        int objStart = StringFind(sigArr, "{", pos);
        if(objStart < 0) break;
        int objEnd = StringFind(sigArr, "}", objStart);
        if(objEnd < 0) break;

        string obj = StringSubstr(sigArr, objStart, objEnd - objStart + 1);
        pos = objEnd + 1;

        string direction = ExtractString(obj, "direction");
        double entry = ExtractDouble(obj, "entry");
        double sl = ExtractDouble(obj, "sl");
        double tp = ExtractDouble(obj, "tp");
        string strategy = ExtractString(obj, "strategy");
        string timeStr = ExtractString(obj, "time");

        if(entry <= 0) continue;

        color sigColor = (direction == "SELL") ? SellSignalColor : BuySignalColor;
        int arrowCode = (direction == "SELL") ? 234 : 233;

        string name = PREFIX + "SIG_" + IntegerToString(idx);
        ObjectCreate(0, name, OBJ_ARROW, 0, TimeCurrent(), entry);
        ObjectSetInteger(0, name, OBJPROP_ARROWCODE, arrowCode);
        ObjectSetInteger(0, name, OBJPROP_COLOR, sigColor);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, 3);
        ObjectSetString(0, name, OBJPROP_TOOLTIP, strategy + " " + direction + " @ " + DoubleToString(entry, 5));

        if(sl > 0)
        {
            string slName = PREFIX + "SL_" + IntegerToString(idx);
            ObjectCreate(0, slName, OBJ_HLINE, 0, 0, sl);
            ObjectSetInteger(0, slName, OBJPROP_COLOR, clrRed);
            ObjectSetInteger(0, slName, OBJPROP_STYLE, STYLE_DASHDOT);
            ObjectSetInteger(0, slName, OBJPROP_WIDTH, 1);
            ObjectSetString(0, slName, OBJPROP_TOOLTIP, "SL: " + DoubleToString(sl, 5));
        }

        if(tp > 0)
        {
            string tpName = PREFIX + "TP_" + IntegerToString(idx);
            ObjectCreate(0, tpName, OBJ_HLINE, 0, 0, tp);
            ObjectSetInteger(0, tpName, OBJPROP_COLOR, clrLime);
            ObjectSetInteger(0, tpName, OBJPROP_STYLE, STYLE_DASHDOT);
            ObjectSetInteger(0, tpName, OBJPROP_WIDTH, 1);
            ObjectSetString(0, tpName, OBJPROP_TOOLTIP, "TP: " + DoubleToString(tp, 5));
        }

        idx++;
    }
}

//+------------------------------------------------------------------+
// Helper functions for JSON parsing
//+------------------------------------------------------------------+
string ExtractString(string json, string key)
{
    string searchKey = "\"" + key + "\"";
    int keyPos = StringFind(json, searchKey);
    if(keyPos < 0) return "";

    int colonPos = StringFind(json, ":", keyPos);
    if(colonPos < 0) return "";

    int quoteStart = StringFind(json, "\"", colonPos + 1);
    if(quoteStart < 0) return "";

    int quoteEnd = StringFind(json, "\"", quoteStart + 1);
    if(quoteEnd < 0) return "";

    return StringSubstr(json, quoteStart + 1, quoteEnd - quoteStart - 1);
}

string ExtractStringAfter(string json, string key, int startPos)
{
    int keyPos = StringFind(json, key, startPos);
    if(keyPos < 0) return "";

    int colonPos = StringFind(json, ":", keyPos);
    if(colonPos < 0) return "";

    int quoteStart = StringFind(json, "\"", colonPos + 1);
    if(quoteStart < 0) return "";

    int quoteEnd = StringFind(json, "\"", quoteStart + 1);
    if(quoteEnd < 0) return "";

    return StringSubstr(json, quoteStart + 1, quoteEnd - quoteStart - 1);
}

double ExtractDouble(string json, string key)
{
    string searchKey = "\"" + key + "\"";
    int keyPos = StringFind(json, searchKey);
    if(keyPos < 0) return 0;

    int colonPos = StringFind(json, ":", keyPos);
    if(colonPos < 0) return 0;

    int numStart = colonPos + 1;
    while(numStart < StringLen(json) && (StringGetCharacter(json, numStart) == ' ' || StringGetCharacter(json, numStart) == '\t'))
        numStart++;

    int numEnd = numStart;
    while(numEnd < StringLen(json))
    {
        int ch = StringGetCharacter(json, numEnd);
        if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-')
            numEnd++;
        else
            break;
    }

    string numStr = StringSubstr(json, numStart, numEnd - numStart);
    return StringToDouble(numStr);
}

int FindMatchingBracket(string json, int openPos)
{
    if(openPos < 0) return -1;
    int depth = 0;
    int len = StringLen(json);
    for(int i = openPos; i < len; i++)
    {
        int ch = StringGetCharacter(json, i);
        if(ch == '[') depth++;
        else if(ch == ']') { depth--; if(depth == 0) return i; }
    }
    return -1;
}
//+------------------------------------------------------------------+
