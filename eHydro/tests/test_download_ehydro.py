"""API batching, literal channel prefixes, transfer failures, and repeatable downloads."""
import json
from pathlib import Path

import pytest
import requests

from eHydro import download_ehydro as ehydro


LAYER = 'https://example.test/FeatureServer/0'
URL = 'https://data.example.test/survey.zip'


class Response:
    def __init__(self, payload=None, chunks=(b'survey data',), headers=None):
        self.payload = payload
        self.chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def survey(oid, channel='CEMVK_LM_1', url=URL):
    return dict(OBJECTID=oid, channelareaidfk=channel, usacedistrictcode='CEMVK',
                surveyjobidpk=f'survey-{oid}', sourcedatalocation=url,
                surveydatestart=1735689600000, surveydateend=1735776000000,
                sourceprojection='EPSG:26915', sdsfeaturename='Lower Mississippi')


class Session:
    def __init__(self, records, packages=None, truncate=False, omit=False):
        self.records = {record['OBJECTID']: record for record in records}
        self.packages = packages or {URL: Response()}
        self.calls = []
        self.truncate, self.omit = truncate, omit

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == LAYER:
            names = ['OBJECTID', 'usacedistrictcode', 'surveydatestart', 'sourcedatalocation', 'channelareaidfk']
            return Response(dict(fields=[{'name': name} for name in names], maxRecordCount=2,
                                 objectIdField='OBJECTID'))
        if url == LAYER+'/query':
            params = kwargs['params']
            if params.get('returnIdsOnly'):
                return Response(dict(objectIds=list(self.records), objectIdFieldName='OBJECTID'))
            ids = list(map(int, params['objectIds'].split(',')))
            if self.truncate and len(ids) > 1:
                return Response(dict(features=[], exceededTransferLimit=True))
            if self.omit:
                ids = ids[:-1]
            return Response(dict(features=[{'attributes': self.records[oid]} for oid in ids]))
        result = self.packages[url]
        if isinstance(result, Exception):
            raise result
        return result


def args(output, *extra):
    return ehydro.parse_args(['--layer', LAYER, '--output', str(output), *extra])


def test_star_patterns_keep_underscores_literal_and_match_both_districts():
    patterns = ['CEMVK_LM_*', 'CEMVM_LM_*']
    assert ehydro.matches_channel(survey(1, 'cemvk_lm_001'), patterns)
    assert ehydro.matches_channel(survey(2, 'CEMVM_LM_890'), patterns)
    assert not ehydro.matches_channel(survey(3, 'CEMVKxLMx001'), patterns)
    assert not ehydro.matches_channel(survey(4, 'CEMVK_YAZOO_1'), patterns)
    assert not ehydro.matches_channel(survey(5, None), patterns)


@pytest.mark.parametrize('truncate', [False, True])
def test_discovery_batches_every_id_and_uses_acquisition_year_boundaries(truncate):
    session = Session([survey(i) for i in range(5)], truncate=truncate)
    records, where = ehydro.discover_surveys(session, LAYER, ['MVK', 'MVM'], 2025, 'channelareaidfk')
    assert len(records) == 5 and {record['objectid'] for record in records} == set(range(5))
    assert "usacedistrictcode IN ('CEMVK', 'CEMVM')" in where
    assert "surveydatestart >= TIMESTAMP '2025-01-01 00:00:00'" in where
    assert "surveydatestart < TIMESTAMP '2026-01-01 00:00:00'" in where
    assert all('returnGeometry' in kw['params'] for url, kw in session.calls
               if 'objectIds' in kw.get('params', {}))


def test_incomplete_batch_and_arcgis_http_200_error_are_failures():
    with pytest.raises(RuntimeError, match='incomplete'):
        ehydro.discover_surveys(Session([survey(1), survey(2)], omit=True), LAYER,
                                ['MVK', 'MVM'], 2025, 'channelareaidfk')

    class ErrorSession:
        def get(self, *args, **kwargs):
            return Response({'error': {'code': 400, 'message': 'Invalid query', 'details': []}})

    with pytest.raises(RuntimeError, match='ArcGIS error 400'):
        ehydro.api_json(ErrorSession(), LAYER)


def test_catalog_mode_lists_all_channels_but_never_downloads_packages(tmp_path, capsys):
    session = Session([survey(1), survey(2, 'CEMVK_YAZOO_1'), survey(3, None)])
    assert ehydro.run(args(tmp_path, '--list-channels'), session) == 0
    report = json.loads((tmp_path/'manifest.json').read_text())
    assert report['candidate_count'] == 3 and report['matched_count'] == 1
    assert report['surveys'][0]['status'] == 'catalog_only'
    assert 'CEMVK_YAZOO_1' in capsys.readouterr().out
    assert '(missing)' in (tmp_path/'channels.csv').read_text()
    assert not (tmp_path/'files').exists() and not any(url == URL for url, _ in session.calls)


def test_duplicate_urls_download_once_and_reruns_verify_local_files(tmp_path):
    records = [survey(1), survey(2, 'CEMVM_LM_2')]
    first = Session(records)
    assert ehydro.run(args(tmp_path), first) == 0
    assert sum(url == URL for url, _ in first.calls) == 1
    report = json.loads((tmp_path/'manifest.json').read_text())
    assert all(record['status'] == 'downloaded' for record in report['surveys'])
    saved = tmp_path/report['surveys'][0]['file']
    assert saved.read_bytes() == b'survey data'
    assert report['surveys'][0]['surveydatestart'] == '2025-01-01T00:00:00+00:00'
    second = Session(records)
    assert ehydro.run(args(tmp_path), second) == 0
    assert not any(url == URL for url, _ in second.calls)
    report = json.loads((tmp_path/'manifest.json').read_text())
    assert all(record['status'] == 'verified_existing' for record in report['surveys'])
    saved.write_bytes(b'corrupt')
    assert ehydro.run(args(tmp_path), Session(records)) == 1
    assert saved.read_bytes() == b'corrupt'


def test_missing_urls_and_transfer_errors_are_reported_while_other_files_complete(tmp_path):
    bad = 'https://data.example.test/fail.zip'
    records = [survey(1), survey(2, url=bad), survey(3, url=None)]
    session = Session(records, packages={URL: Response(), bad: requests.HTTPError('503 Service unavailable')})
    assert ehydro.run(args(tmp_path), session) == 1
    report = json.loads((tmp_path/'manifest.json').read_text())
    assert [record['status'] for record in report['surveys']] == ['downloaded', 'failed', 'missing_url']
    assert len(list((tmp_path/'files').iterdir())) == 1
    assert '503 Service unavailable' in (tmp_path/'manifest.csv').read_text()


@pytest.mark.parametrize('response', [
    Response(chunks=(b'partial', requests.ConnectionError('stream interrupted'))),
    Response(chunks=(b'partial',), headers={'Content-Length': '1000'}),
    Response(chunks=()),
    Response(chunks=(b'<!doctype html><html>login</html>',)),
    Response(headers={'Content-Type': 'text/html'}),
])
def test_bad_transfers_leave_no_completed_file_or_temporary_bytes(tmp_path, response):
    with pytest.raises((requests.RequestException, RuntimeError)):
        ehydro.download_package(Session([], packages={URL: response}), URL, tmp_path)
    assert not list(tmp_path.iterdir())


def test_unverified_existing_file_and_unrelated_manifest_are_preserved(tmp_path):
    path = tmp_path/ehydro.package_name(URL)
    path.write_bytes(b'keep this file')
    session = Session([])
    with pytest.raises(RuntimeError, match='preserving'):
        ehydro.download_package(session, URL, tmp_path)
    assert path.read_bytes() == b'keep this file' and not session.calls
    manifest = tmp_path/'manifest.json'
    manifest.write_text('{"user": "keep"}')
    with pytest.raises(RuntimeError, match='unrelated manifest'):
        ehydro.run(args(tmp_path), session)
    assert manifest.read_text() == '{"user": "keep"}'


def test_zero_matches_writes_inventory_and_returns_nonzero(tmp_path):
    assert ehydro.run(args(tmp_path), Session([survey(1, 'CEMVK_OTHER_1')])) == 2
    report = json.loads((tmp_path/'manifest.json').read_text())
    assert report['matched_count'] == 0 and report['candidate_count'] == 1
    assert not (tmp_path/'files').exists()


def test_package_names_are_safe_and_do_not_collide_for_same_remote_basename():
    assert ehydro.package_name(URL) != ehydro.package_name(URL.replace('data.', 'other.'))
    name = ehydro.package_name('https://data.example.test/%2e%2e%2f%5cunsafe.zip')
    assert Path(name).name == name and '/' not in name and '\\' not in name
