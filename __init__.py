"""Wake plugin. This loop thread is fixed; the logic lives in engine.py, reloaded whenever that file
changes. platform.py registers the "Wake Agent" cron delivery target. CLI: cli.py."""
import fcntl, importlib.util, logging, threading, time
from pathlib import Path

log = logging.getLogger("plugins.wake")
HERE = Path(__file__).resolve().parent


def _load(name, tag=""):
    spec = importlib.util.spec_from_file_location(f"wake_{name}{tag}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _engine(cache):
    mt = (HERE / "engine.py").stat().st_mtime
    if cache.get("mt") != mt:
        cache.update(mt=mt, mod=_load("engine", "_%d" % int(mt * 1000)))
        log.info("wake engine loaded")
    return cache["mod"]


def _loop(ctx):
    held, cache = None, {}
    while True:
        try:
            eng = _engine(cache)
            d = eng.state_dir(); d.mkdir(parents=True, exist_ok=True)
            if held is None and ctx._manager._gateway_message_injector:
                f = open(d / "loop.lock", "a+")  # one delivering loop per profile
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); held = f
                except OSError:
                    f.close()
            if held is not None:
                (d / "heartbeat").write_text(str(time.time()))
                eng.tick(ctx)
        except Exception:
            log.warning("wake tick failed", exc_info=True)
        time.sleep(5)


def register(ctx):
    try:
        _load("platform").register(ctx)
    except Exception:
        log.warning("wake_agent delivery target not registered", exc_info=True)
    threading.Thread(target=_loop, args=(ctx,), name="wake-plugin", daemon=True).start()
