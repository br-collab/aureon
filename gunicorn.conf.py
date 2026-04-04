# Gunicorn configuration for Railway deployment.
# post_fork runs in each worker process after it forks from the master,
# which is after gunicorn is bound and ready to accept connections.
# This ensures background threads start only after Flask is serving.

def post_fork(server, worker):
    from server import _start_background_threads
    _start_background_threads()
