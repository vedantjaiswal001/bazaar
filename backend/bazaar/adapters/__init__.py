"""Protocol adapters: translate an external agent-payment rail into BAZAAR's
canonical domain (a signed Mandate + TransactionRequest) so the ONE deterministic
gate authorises every rail. Adapters verify authenticity; the gate enforces money.
"""
