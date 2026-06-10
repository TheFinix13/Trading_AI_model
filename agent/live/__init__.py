"""Live trading module — real-time signal detection and execution.

Usage:
    from agent.live.signal_loop import SignalLoop
    from agent.live.broker import PaperBroker, MT5Broker, ExnessDemoBroker, create_broker
    from agent.live.monitor import PositionMonitor
    from agent.live.config import LiveConfig
"""
from agent.live.broker import (
    AccountInfo,
    BrokerConnection,
    ExnessDemoBroker,
    MT5Broker,
    OrderResult,
    PaperBroker,
    Position,
    create_broker,
)
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.live.signal_loop import SignalLoop

__all__ = [
    "AccountInfo",
    "BrokerConnection",
    "ExnessDemoBroker",
    "LiveConfig",
    "MT5Broker",
    "OrderResult",
    "PaperBroker",
    "Position",
    "PositionMonitor",
    "SignalLoop",
    "create_broker",
]
