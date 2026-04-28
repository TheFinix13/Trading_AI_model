from pathlib import Path

from agent.data.csv_import import import_csv_to_cache, load_csv
from agent.data.source import ParquetCache
from agent.types import Timeframe


def test_load_mt5_style_csv(tmp_path: Path):
    csv = tmp_path / "EURUSD_H1.csv"
    csv.write_text(
        "Date,Time,Open,High,Low,Close,Volume\n"
        "2024.01.01,00:00,1.10000,1.10100,1.09950,1.10050,1234\n"
        "2024.01.01,01:00,1.10050,1.10200,1.10000,1.10150,2345\n"
    )
    df = load_csv(csv)
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == 1.10050


def test_load_histdata_style(tmp_path: Path):
    csv = tmp_path / "DAT_ASCII_EURUSD_M15_2024.csv"
    csv.write_text(
        "20240102 070000;1.10000;1.10080;1.09980;1.10050;120\n"
        "20240102 071500;1.10050;1.10100;1.10010;1.10080;95\n"
    )
    df = load_csv(csv)
    assert len(df) == 2
    assert df.iloc[1]["high"] == 1.10100


def test_import_to_cache_merges(tmp_path: Path):
    csv = tmp_path / "merge.csv"
    csv.write_text(
        "datetime,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,1.10,1.11,1.09,1.105,100\n"
    )
    n = import_csv_to_cache(csv, "EURUSD", Timeframe.H1, tmp_path)
    assert n == 1
    csv2 = tmp_path / "merge2.csv"
    csv2.write_text(
        "datetime,open,high,low,close,volume\n"
        "2024-01-01T01:00:00Z,1.105,1.115,1.10,1.11,200\n"
    )
    n = import_csv_to_cache(csv2, "EURUSD", Timeframe.H1, tmp_path)
    assert n == 2

    cache = ParquetCache(tmp_path)
    df = cache.load("EURUSD", Timeframe.H1)
    assert len(df) == 2
