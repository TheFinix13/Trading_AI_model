"""Phase-1 strategy shims.

Each module here wraps an existing detector and exposes a `Strategy`
subclass that produces tagged `Setup` candidates. See section 4 of
`docs/regime_router_design.md` for the taxonomy.
"""
from agent.strategy.strategies.bos_continuation import BOSContinuation
from agent.strategy.strategies.fib_retracement import FibRetracement
from agent.strategy.strategies.fvg_retest import FVGRetest
from agent.strategy.strategies.liquidity_grab_reversal import LiquidityGrabReversal
from agent.strategy.strategies.sd_zone_retest import SDZoneRetest

__all__ = [
    "BOSContinuation",
    "FibRetracement",
    "FVGRetest",
    "LiquidityGrabReversal",
    "SDZoneRetest",
]
