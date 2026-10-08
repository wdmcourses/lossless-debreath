import sys
import time

_WIDTH = 28
_LABEL = 16


class Progress:
    def __init__(self, label, stream=None, enabled=None):
        self.label = label[:_LABEL]
        self.stream = stream if stream is not None else sys.stderr
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.total = 0
        self.last = 0.0
        self.shown = False

    def start(self, total):
        self.total = max(0, int(total))
        self.update(0, force=True)

    def update(self, done, force=False):
        if not self.enabled:
            return
        now = time.time()
        if not force and now - self.last < 0.1 and (self.total == 0 or done < self.total):
            return
        self.last = now
        self._render(done)

    def _render(self, done):
        if self.total:
            frac = min(1.0, max(0.0, done / float(self.total)))
            filled = int(round(frac * _WIDTH))
            bar = "#" * filled + "-" * (_WIDTH - filled)
            text = "\r%-*s [%s] %3d%%" % (_LABEL, self.label, bar, int(frac * 100))
        else:
            text = "\r%-*s %d" % (_LABEL, self.label, done)
        self.stream.write(text)
        self.stream.flush()
        self.shown = True

    def close(self):
        if self.enabled and self.shown:
            self._render(self.total or 0)
            self.stream.write("\n")
            self.stream.flush()
