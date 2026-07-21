"""Security test suite -- activated in Sprint 1 per D048.

Every feature that touches auth / credentials / broker-connection lands
a test module here. Tests run in the same pytest suite as the rest --
no separate CI. A failing security test is a hard block on ship.

See ``company/protocols/review-chain.md`` §6 for the security stage
review-chain contract.
"""
