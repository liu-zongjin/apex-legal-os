"""Complete CPython 3.12 Proactor cleanup after Windows resets a closing socket."""
import sys


def _close_with_reset_recovery(original, transport, exc):
    try:
        return original(transport, exc)
    except OSError as error:
        # CPython has already called protocol.connection_lost() at this point.
        # Its subsequent socket.shutdown() can raise WSAECONNRESET and skip
        # closing the socket and detaching it from asyncio.Server. Uvicorn then
        # waits forever for that connection on a cooperative shutdown.
        if getattr(error, 'winerror', None) != 10054 or transport._sock is None:
            raise
        try:
            transport._sock.close()
        finally:
            transport._sock = None
            server = transport._server
            if server is not None:
                server._detach()
                transport._server = None
            transport._called_connection_lost = True


def install():
    if sys.platform != 'win32':
        return
    from asyncio.proactor_events import _ProactorBasePipeTransport
    original = _ProactorBasePipeTransport._call_connection_lost
    if getattr(original, '_stella_reset_recovery', False):
        return
    def recover(transport, exc):
        return _close_with_reset_recovery(original, transport, exc)
    recover._stella_reset_recovery = True
    _ProactorBasePipeTransport._call_connection_lost = recover
