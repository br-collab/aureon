# Gunicorn configuration for Railway deployment.
# post_fork runs in each worker process after it forks from the master,
# which is after gunicorn is bound and ready to accept connections.
# This ensures background threads start only after Flask is serving.

# Phase 2 P2-2: MMF Lane D atomic DvP runs real XRPL testnet
# transactions in the request path. register_investor can take up
# to ~60s (fund setup + investor setup, each ~5-9s per tx × 4-7
# txs). execute_subscription_dvp takes ~15-25s. Default gunicorn
# worker timeout is 30s; we raise it here so XRPL work doesn't get
# SIGKILL'd mid-flight. Phase 3+ moves XRPL work to a background
# job queue so the request path stays snappy again.
timeout = 120


def post_fork(server, worker):
    from server import _start_background_threads
    _start_background_threads()
