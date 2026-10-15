"""Select eHydro packages, estimate transfers, and monitor restartable downloads."""
import argparse
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QThread, QTimer, QSignalBlocker, Signal, Slot
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

if __package__:
    from . import download_ehydro as core
    from .transfer_progress import format_duration, format_size
else:
    import download_ehydro as core
    from transfer_progress import format_duration, format_size


class Operation(QThread):
    progress = Signal(object)

    def __init__(self, function, parent):
        super().__init__(parent)
        self.function = function
        self.cancel_event = threading.Event()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.function(self.progress.emit, self.cancel_event.is_set)
        except Exception as exc:
            self.error = exc


STATUS = {'ready': 'Ready', 'catalog_only': 'Ready', 'pending': 'Ready',
          'verified_existing': 'Already downloaded · verified', 'downloaded': 'Downloaded',
          'size_unknown': 'Size unavailable', 'needs_review': 'Existing file needs review',
          'missing_url': 'No download URL', 'failed': 'Failed', 'cancelled': 'Stopped',
          'not_selected': 'Not selected'}


def remaining_selection(packages, urls):
    remaining = [p for p in packages if p['url'] in urls and
                 p.get('local_status') != 'verified_existing' and
                 not all(s.get('status') in {'downloaded', 'verified_existing'} for s in p['surveys'])]
    return (sum(p.get('size_bytes') or 0 for p in remaining),
            sum(p.get('size_bytes') is None for p in remaining), len(remaining))


class DownloadWindow(QMainWindow):
    def __init__(self, args=None, session_factory=None, auto_discover=True):
        super().__init__()
        self.args = args or core.parse_args([])
        self.session_factory = session_factory or core.session_with_retries
        self.report = None
        self.available_years = None
        self.auto_destination = self.args.output == Path('output/ehydro_lmr_2025')
        self.packages = []
        self.worker = None
        self.operation = None
        self.close_pending = False
        self.filling = False
        self.setWindowTitle('eHydro · Lower Mississippi survey downloader')
        self.resize(1450, 1000)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel('eHydro survey downloads')
        title.setStyleSheet('font-size: 22px; font-weight: bold; color: #173e58; padding: 6px;')
        layout.addWidget(title)
        note = QLabel('Find matching survey archives, review their included files, then choose what to download. '
                      'All available packages start checked; verified local files are skipped automatically.')
        note.setWordWrap(True)
        layout.addWidget(note)

        self.settings = QWidget()
        controls = QGridLayout(self.settings)
        controls.setContentsMargins(0, 4, 0, 4)
        self.year = QComboBox()
        self.year.addItem('Discovering available years…', None)
        self.year.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.year.setMinimumContentsLength(22)
        self.years_button = QPushButton('Refresh available years')
        self.years_button.clicked.connect(self.refresh_years)
        self.mvk, self.mvm = QCheckBox('MVK · Vicksburg'), QCheckBox('MVM · Memphis')
        self.mvk.setChecked('MVK' in self.args.districts)
        self.mvm.setChecked('MVM' in self.args.districts)
        district_row = QHBoxLayout()
        district_row.addWidget(self.mvk)
        district_row.addWidget(self.mvm)
        district_row.addStretch()
        controls.addWidget(QLabel('Survey start year'), 0, 0)
        controls.addWidget(self.year, 0, 1)
        controls.addWidget(self.years_button, 0, 2)
        controls.addLayout(district_row, 0, 3, 1, 2)
        self.patterns = QLineEdit('; '.join(self.args.channel_pattern or
                                          [f'CE{d}_LM_*' for d in self.args.districts]))
        self.patterns.setToolTip('Separate channel patterns with semicolons. * matches any sequence; underscores are literal.')
        controls.addWidget(QLabel('Channel patterns'), 1, 0)
        controls.addWidget(self.patterns, 1, 1, 1, 4)
        self.destination = QLineEdit(str(self.args.output.expanduser().resolve()))
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        controls.addWidget(QLabel('Destination folder'), 2, 0)
        controls.addWidget(self.destination, 2, 1, 1, 3)
        controls.addWidget(browse, 2, 4)
        layout.addWidget(self.settings)
        self.years_label = QLabel('Available acquisition years will be discovered for the selected districts and channel patterns.')
        self.years_label.setWordWrap(True)
        layout.addWidget(self.years_label)

        actions = QHBoxLayout()
        self.find_button = QPushButton('Find files')
        self.find_button.clicked.connect(self.discover)
        self.all_button, self.none_button, self.pending_button = (QPushButton('Check all'),
                                                                 QPushButton('Uncheck all'),
                                                                 QPushButton('Check new files only'))
        self.all_button.clicked.connect(lambda: self._check('all'))
        self.none_button.clicked.connect(lambda: self._check('none'))
        self.pending_button.clicked.connect(lambda: self._check('pending'))
        for button in [self.find_button, self.all_button, self.none_button, self.pending_button]:
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(QLabel('Planning speed (Mbps)'))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(.1, 10000)
        self.speed.setValue(self.args.estimate_mbps)
        self.speed.setToolTip('Assumed megabits per second for the estimate before downloading. Actual ETA uses measured transfer speed.')
        self.speed.valueChanged.connect(self._estimate)
        actions.addWidget(self.speed)
        layout.addLayout(actions)

        self.inventory_label = QLabel('Click Find files to report every matching archive and its contents.')
        self.inventory_label.setWordWrap(True)
        layout.addWidget(self.inventory_label)
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Get', 'Archive / package', 'District', 'Channel',
                                             'Survey start (UTC)', 'Size', 'Status', 'Included files'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._details)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for index, width in enumerate([45, 330, 90, 175, 165, 100, 205, 260]):
            self.table.setColumnWidth(index, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        split.addWidget(self.table)
        details_tabs = QTabWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Select a package to inspect its complete filename, download URL and included file list.')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        details_tabs.addTab(self.details, 'Selected package details')
        details_tabs.addTab(self.log, 'Transfer log')
        split.addWidget(details_tabs)
        split.setSizes([440, 150])
        layout.addWidget(split, 1)
        self.estimate_label = QLabel()
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)
        self.current_label = QLabel('No transfers started.')
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)
        self.file_progress = QProgressBar()
        self.overall_progress = QProgressBar()
        self.file_progress.setFormat('Current file: %p%')
        self.overall_progress.setFormat('Selected files: %p%')
        layout.addWidget(self.file_progress)
        layout.addWidget(self.overall_progress)
        self.transfer_label = QLabel('ETA appears after selection; measured ETA updates while downloading.')
        self.transfer_label.setWordWrap(True)
        layout.addWidget(self.transfer_label)
        bottom = QHBoxLayout()
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.download_button = QPushButton('Download checked files')
        self.download_button.clicked.connect(self.download)
        self.download_button.setStyleSheet('background: #206688; color: white; padding: 9px; font-weight: bold;')
        self.stop_button = QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop)
        bottom.addWidget(self.download_button)
        bottom.addWidget(self.stop_button)
        layout.addLayout(bottom)
        self.year.currentIndexChanged.connect(self._year_changed)
        self.mvk.toggled.connect(self._invalidate_years)
        self.mvm.toggled.connect(self._invalidate_years)
        self.patterns.textChanged.connect(self._invalidate_years)
        self.destination.textChanged.connect(self._invalidate)
        self.destination.textEdited.connect(self._custom_destination)
        self._busy(False)
        self._estimate()
        if auto_discover:
            QTimer.singleShot(0, self.refresh_years)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose download destination', self.destination.text())
        if path:
            self.auto_destination = False
            self.destination.setText(path)

    def _custom_destination(self, *args):
        self.auto_destination = False

    def _clear_inventory(self):
        self.report = None
        self.packages = []
        self.table.setRowCount(0)
        self.details.clear()
        self.download_button.setEnabled(False)
        self.file_progress.setRange(0, 1000)
        self.file_progress.setValue(0)
        self.overall_progress.setRange(0, 1000)
        self.overall_progress.setValue(0)
        self.current_label.setText('No transfers started for this selection.')
        self.transfer_label.setText('ETA updates after the selected year’s files are listed.')

    def _invalidate_years(self, *args):
        self._clear_inventory()
        self.available_years = None
        with QSignalBlocker(self.year):
            self.year.clear()
            self.year.addItem('Refresh available years…', None)
        self.years_label.setText('District or channel filters changed. Click Refresh available years.')
        self._busy(False)
        self._estimate()

    def _year_changed(self, *args):
        self._clear_inventory()
        year = self.year.currentData()
        if year is not None:
            if self.auto_destination:
                self.destination.setText(str((Path('output')/f'ehydro_lmr_{year}').resolve()))
            self.inventory_label.setText(f'Loading matching packages for {year}…')
            QTimer.singleShot(0, self.discover)
        self._busy(False)
        self._estimate()

    def _invalidate(self, *args):
        self.report = None
        self.download_button.setEnabled(False)
        self.estimate_label.setText('Settings changed. Click Find files to refresh the inventory and check this destination.')

    def _options(self, require_year=True):
        values = vars(self.args).copy()
        values.update(year=self.year.currentData(), districts=[code for code, box in [('MVK', self.mvk), ('MVM', self.mvm)] if box.isChecked()],
                      channel_pattern=[p.strip() for p in self.patterns.text().split(';') if p.strip()],
                      output=Path(self.destination.text()).expanduser().resolve(), catalog_only=True, list_channels=False)
        if not values['districts'] or not values['channel_pattern']:
            raise ValueError('Choose at least one district and a channel pattern.')
        if require_year and (values['year'] is None or not self.destination.text().strip()):
            raise ValueError('Choose an available survey year and a destination folder.')
        return argparse.Namespace(**values)

    def _busy(self, busy):
        self.settings.setEnabled(not busy)
        self.year.setEnabled(not busy and self.available_years is not None and bool(self.available_years['years']))
        self.find_button.setEnabled(not busy and self.year.currentData() is not None)
        for widget in [self.all_button, self.none_button, self.pending_button]:
            widget.setEnabled(not busy)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if item.data(Qt.UserRole) and not busy:
                flags |= Qt.ItemIsUserCheckable
            item.setFlags(flags)
        self.stop_button.setEnabled(busy)
        self.download_button.setEnabled(not busy and self.report is not None and bool(self.selected_urls()))

    def _start(self, name, function):
        if self.worker is not None:
            return
        self.operation = name
        self.worker = Operation(function, self)
        self.worker.progress.connect(self._progress, Qt.QueuedConnection)
        self.worker.finished.connect(self._finished, Qt.QueuedConnection)
        self._busy(True)
        self.worker.start()

    def discover(self):
        if self.worker is not None:
            return
        try:
            args = self._options()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.report = None
        self.status.setText('Discovering matching surveys…')
        self.overall_progress.setRange(0, 0)

        def task(notify, cancelled):
            with self.session_factory() as session:
                report = core.prepare_report(args, session, cancelled)
                notify(dict(kind='catalog', packages=core.package_inventory(report)))
                core.inspect_packages(report, args.output, session, notify, cancelled)
                return report
        self._start('inventory', task)

    def refresh_years(self):
        if self.worker is not None:
            return
        try:
            args = self._options(require_year=False)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._invalidate_years()
        self.status.setText('Discovering all available acquisition years for these channels…')
        self.overall_progress.setRange(0, 0)

        def task(notify, cancelled):
            with self.session_factory() as session:
                return core.discover_available_years(session, args.layer, args.districts,
                                                     args.channel_pattern, args.channel_field, cancelled)
        self._start('years', task)

    def _show_years(self, available):
        self.available_years = available
        with QSignalBlocker(self.year):
            self.year.clear()
            self.year.addItem('Select a year…' if available['years'] else 'No available data', None)
            for item in available['years']:
                districts = ', '.join(f'{name}: {count}' for name, count in item['districts'].items())
                self.year.addItem(f'{item["year"]} — {item["packages"]} packages ({districts})', item['year'])
        summary = ', '.join(f'{item["year"]} ({item["packages"]})' for item in available['years']) or 'none'
        text = 'Available acquisition years (data packages): '+summary+'.'
        if available['missing_dates'] or available['missing_urls']:
            text += (f' Excluded: {available["missing_urls"]} surveys without data links; '
                     f'{available["missing_dates"]} linked surveys without usable acquisition dates.')
        self.years_label.setText(text)
        self.log.appendPlainText(text)
        self.status.setText('Choose a year to list its files.' if available['years'] else
                            'No dated data-package links match these districts and channel patterns.')
        self.inventory_label.setText('Choose an available year; files will be listed before any downloads start.')

    def selected_urls(self):
        return {self.table.item(row, 0).data(Qt.UserRole) for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == Qt.Checked and self.table.item(row, 0).data(Qt.UserRole)}

    def _fill(self, packages, checked=None):
        self.filling = True
        self.packages = packages
        self.table.setRowCount(0)
        for package in packages:
            surveys, url = package['surveys'], package['url']
            row = self.table.rowCount()
            self.table.insertRow(row)
            box = QTableWidgetItem()
            box.setData(Qt.UserRole, url)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if url and self.worker is None:
                flags |= Qt.ItemIsUserCheckable
            box.setFlags(flags)
            box.setCheckState(Qt.Checked if url and (checked is None or url in checked) else Qt.Unchecked)
            self.table.setItem(row, 0, box)
            status = package.get('local_status', 'ready') if url else 'missing_url'
            current = [s.get('status') for s in surveys]
            if current and current[0] in {'downloaded', 'verified_existing', 'failed', 'cancelled', 'not_selected'}:
                status = current[0]
            contents = '\n'.join(dict.fromkeys(s.get('sourcedatacontent') or '(not listed)' for s in surveys))
            values = [package['filename'], ', '.join(sorted({s.get('usacedistrictcode', '') for s in surveys})),
                      ', '.join(sorted({s.get('channel_id') or '' for s in surveys})),
                      ', '.join(sorted({s.get('surveydatestart') or '' for s in surveys})),
                      format_size(package.get('size_bytes')), STATUS.get(status, status), contents]
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setToolTip(value if column != 6 else package.get('inspection_error', value))
                self.table.setItem(row, column, item)
        self.filling = False
        self.inventory_label.setText(f'{len(packages)} matching packages reported. '
                                     'Select a row for its full contents and metadata. Sizes marked Unknown remain downloadable.')
        self._estimate()

    def _check(self, mode):
        self.filling = True
        existing = {p['url'] for p in self.packages if p.get('local_status') == 'verified_existing' or
                    all(s.get('status') in {'downloaded', 'verified_existing'} for s in p['surveys'])}
        for row in range(self.table.rowCount()):
            box = self.table.item(row, 0)
            url = box.data(Qt.UserRole)
            box.setCheckState(Qt.Checked if url and mode != 'none' and (mode != 'pending' or url not in existing) else Qt.Unchecked)
        self.filling = False
        self._estimate()

    def _item_changed(self, item):
        if not self.filling and item.column() == 0:
            self._estimate()

    def _estimate(self, *args):
        if not hasattr(self, 'estimate_label'):
            return
        if self.report is None and not self.packages:
            self.estimate_label.setText('Select an available year to list its files and estimate download time.')
            self.download_button.setEnabled(False)
            return
        selected = self.selected_urls()
        size, unknown, pending = remaining_selection(self.packages, selected)
        estimate = size/(self.speed.value()*1e6/8)
        size_text = ('at least ' if unknown else '') + format_size(size)
        eta = ('at least ' if unknown else '~') + format_duration(estimate)
        self.estimate_label.setText(f'{len(selected)} checked · {pending} need transfer · {size_text} remaining'
                                    + (f' + {unknown} unknown-size files' if unknown else '')
                                    + f' · estimated time {eta} at {self.speed.value():g} Mbps (assumed).')
        self.download_button.setEnabled(self.worker is None and self.report is not None and bool(selected))

    def _details(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.packages):
            return
        package = self.packages[row]
        lines = [package['filename'], 'Download: '+(package['url'] or '(missing)'), '']
        for survey in package['surveys']:
            lines += [f'Survey: {survey.get("surveyjobidpk")}', f'Channel: {survey.get("channel_id")}',
                      f'Date: {survey.get("surveydatestart")}', f'Projection: {survey.get("sourceprojection")}',
                      'Files inside the archive:', (survey.get('sourcedatacontent') or '(not listed)').replace(',', '\n'), '']
        if package.get('inspection_error'):
            lines += ['Inspection note: '+package['inspection_error']]
        self.details.setPlainText('\n'.join(lines))

    def download(self):
        if self.worker is not None or self.report is None:
            return
        urls = self.selected_urls()
        if not urls:
            self.status.setText('Check at least one file to download.')
            return
        report, output = self.report, self._options().output
        self.file_progress.setRange(0, 1000)
        self.file_progress.setValue(0)
        self.overall_progress.setRange(0, 1000)
        self.overall_progress.setValue(0)
        self.status.setText('Downloading checked files…')

        def task(notify, cancelled):
            with self.session_factory() as session:
                return core.download_selection(report, urls, output, session, notify, cancelled)
        self._start('download', task)

    @Slot(object)
    def _progress(self, event):
        if event['kind'] == 'catalog':
            self._fill(event['packages'])
            return
        if event['kind'] == 'inventory':
            self.status.setText(f'Checking sizes and local files {event["index"]}/{event["count"]}: {event["filename"]}')
            return
        filename = urlsplit(event['url']).path.rsplit('/', 1)[-1]
        self.current_label.setText(f'{event["phase"].replace("_", " ").capitalize()}: {filename}')
        self.overall_progress.setRange(0, 1000)
        self.overall_progress.setValue(round(1000*event['fraction']))
        total = event['file_total']
        if event['phase'] == 'verifying' or total is None:
            self.file_progress.setRange(0, 0)
        else:
            self.file_progress.setRange(0, 1000)
            self.file_progress.setValue(1000 if event['kind'] == 'result' and event['result']['status'] in {'downloaded', 'verified_existing'}
                                        else round(1000*min(1, event['file_bytes']/max(1, total))))
        eta = event['eta']
        if eta is None and not event['unknown_sizes']:
            eta = event['remaining_bytes']/(self.speed.value()*1e6/8)
        complete = event['processed'] == event['count']
        source = 'complete' if complete else 'measured' if event['rate'] else 'assumed speed'
        speed = format_size(event['rate'])+'/s' if event['rate'] else 'no new bytes transferred' if complete else 'measuring speed…'
        unknown = f' · {event["unknown_sizes"]} sizes unknown' if event['unknown_sizes'] else ''
        self.transfer_label.setText(f'{event["processed"]}/{event["count"]} packages processed · '
                                    f'{format_size(event["network_bytes"])} transferred · {speed} · '
                                    f'ETA {format_duration(eta)} ({source}){unknown}')
        if event['kind'] == 'result':
            result = event['result']
            self.log.appendPlainText(f'{STATUS.get(result["status"], result["status"])}: {filename}'
                                     + (' — '+result['error'] if result.get('error') else ''))
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.UserRole) == event['url']:
                    self.table.item(row, 6).setText(STATUS.get(result['status'], result['status']))

    @Slot()
    def _finished(self):
        worker, operation = self.worker, self.operation
        checked = self.selected_urls()
        self.worker = None
        if worker.error:
            text = 'Stopped. Completed files will be skipped on the next run.' if isinstance(worker.error, core.DownloadCancelled) else f'Operation failed: {worker.error}'
            self.status.setText(text)
            self.log.appendPlainText(text)
        elif operation == 'years':
            self._show_years(worker.result)
        else:
            self.report = worker.result
            self._fill(core.package_inventory(self.report), checked if operation == 'download' else None)
            if operation == 'inventory':
                self.status.setText('Inventory ready. Review the checked files and click Download checked files.'
                                    if self.packages else 'No matching files. Review the year, districts and channel patterns.')
            else:
                s = self.report['summary']
                self.status.setText(f'{self.report["outcome"].replace("_", " ").capitalize()}: '
                                    f'{s["downloaded"]} downloaded, {s["skipped"]} already present, '
                                    f'{s["failed"]} failed, {s["unfinished"]} unfinished.')
        self.overall_progress.setRange(0, 1000)
        if operation in {'inventory', 'years'}:
            self.overall_progress.setValue(0)
        self.file_progress.setRange(0, 1000)
        self._busy(False)
        self._estimate()
        worker.deleteLater()
        if self.close_pending:
            self.close()

    def stop(self):
        if self.worker is not None:
            self.worker.cancel_event.set()
            self.stop_button.setEnabled(False)
            self.status.setText('Stopping… Waiting for the current network read to return; completed files are preserved.')

    def closeEvent(self, event):
        if self.worker is not None:
            self.close_pending = True
            self.stop()
            event.ignore()
        else:
            super().closeEvent(event)


def launch(args):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = DownloadWindow(args)
    window.show()
    return app.exec()
