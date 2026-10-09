"""Content-addressed, atomic survey profile cache. No pickle or credential storage."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

import pandas as pd

from .core import normalize_profile

SCHEMA = 'bathy-profile-v1'


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    if path.is_file():
        return {'path': str(path), 'sha256': digest_file(path)}
    files = sorted(p for p in path.rglob('*') if p.is_file() and p.suffix.lower() != '.lock')
    if not files:
        raise ValueError(f'No readable dataset files in {path}.')
    return {'path': str(path), 'files': [(str(p.relative_to(path)), digest_file(p)) for p in files]}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def cache_key(source, transect_path, settings):
    return hashlib.sha256(canonical({'schema': SCHEMA, 'source': source,
        'source_fingerprint': fingerprint(source['path']),
        'transects': fingerprint(transect_path), 'settings': settings}).encode()).hexdigest()


class ProfileCache:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, key):
        path = self.directory / f'{key}.json'
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            records = payload['records']
            if payload['schema'] != SCHEMA or payload['key'] != key:
                return None
            if hashlib.sha256(canonical(records).encode()).hexdigest() != payload['records_sha256']:
                return None
            return normalize_profile(pd.DataFrame(records))
        except (ValueError, KeyError, TypeError):
            return None

    def put(self, key, frame):
        frame = normalize_profile(frame)
        records = frame.astype(object).where(frame.notna(), None).to_dict('records')
        payload = {'schema': SCHEMA, 'key': key, 'records': records,
                   'records_sha256': hashlib.sha256(canonical(records).encode()).hexdigest()}
        fd, temporary = tempfile.mkstemp(dir=self.directory, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(canonical(payload))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f'{key}.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
