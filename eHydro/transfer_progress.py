"""Byte accounting and time estimates shared by the desktop and CLI downloads."""
import time


def format_size(value):
    if value is None:
        return 'Unknown'
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if value < 1024 or unit == 'TiB':
            return f'{value:,.1f} {unit}'
        value /= 1024


def format_duration(seconds):
    if seconds is None:
        return 'estimating…'
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:d}:{seconds:02d}'


class TransferMeter:
    def __init__(self, sizes, clock=time.monotonic):
        self.sizes = dict(sizes)
        self.received = {url: 0 for url in sizes}
        self.finished = set()
        self.network_bytes = 0
        self.clock, self.started = clock, clock()

    def update(self, url, received, total, phase):
        if phase == 'downloading':
            self.network_bytes += max(0, received-self.received[url])
            self.received[url] = received
            if total is not None:
                self.sizes[url] = total
        return self.snapshot(url, phase)

    def finish(self, url, result):
        if result['status'] != 'cancelled':
            self.finished.add(url)
        if result.get('bytes') is not None:
            self.sizes[url] = result['bytes']
        return {**self.snapshot(url, result['status']), 'kind': 'result'}

    def snapshot(self, url, phase):
        pending = set(self.sizes)-self.finished
        unknown = sum(self.sizes[key] is None for key in pending)
        remaining = sum(max(0, self.sizes[key]-self.received[key])
                        for key in pending if self.sizes[key] is not None)
        elapsed = self.clock()-self.started
        rate = self.network_bytes/elapsed if elapsed >= .5 and self.network_bytes else None
        if not pending:
            eta = 0.
        else:
            eta = remaining/rate if rate and not unknown else None
        known = all(size is not None for size in self.sizes.values())
        total = sum(size or 0 for size in self.sizes.values())
        if known and total:
            credited = sum(self.sizes[key] for key in self.finished)
            credited += sum(min(self.received[key], self.sizes[key]) for key in pending)
            fraction = credited/total
        else:
            fraction = len(self.finished)/len(self.sizes) if self.sizes else 1.
        return dict(kind='progress', url=url, phase=phase, file_bytes=self.received[url],
                    file_total=self.sizes[url], processed=len(self.finished), count=len(self.sizes),
                    network_bytes=self.network_bytes, rate=rate, eta=eta,
                    unknown_sizes=unknown, remaining_bytes=remaining, fraction=fraction)
