# -*- coding: utf-8 -*-
__title__  = 'Apply\nTranslations'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-27
Description:
    Reads a TSV exported by "Export Names for Translation",
    applies the NewName for every row where it is filled.
    Identifies elements by their ElementId from the Id column —
    safe even if the same name appears multiple times.
How-To:
    1. Edit the TSV in Excel: fill the NewName column where needed.
    2. Save as TSV (UTF-8, tab-separated).
    3. Run this script.
    4. Pick the file.
    5. Confirm the count of renames.
    6. Review the report.
'''

import codecs
import os
import sys
import datetime
from Autodesk.Revit.DB import ElementId, Transaction, SubTransaction
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# Crash-survivable log file (flushed after every rename)
# ------------------------------------------------------------------
log_path = os.path.join(
    os.path.expanduser('~'),
    'apply_translations_{}.log'.format(
        datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    )
)
log_f = codecs.open(log_path, 'w', encoding='utf-8')


def log(msg):
    try:
        log_f.write(msg + '\n')
        log_f.flush()
        try:
            os.fsync(log_f.fileno())   # force disk write — survives crash
        except Exception:
            pass
    except Exception:
        pass


log('Apply Translations started at {}'.format(datetime.datetime.now()))
log('Doc title: {}'.format(doc.Title))
log('Doc path: {}'.format(doc.PathName if doc.PathName else '(unsaved)'))
try:
    log('Active view: id={} name={}'.format(
        uidoc.ActiveView.Id.IntegerValue, uidoc.ActiveView.Name
    ))
except Exception:
    log('Active view: <error>')


# ------------------------------------------------------------------
# Pick input file
# ------------------------------------------------------------------
in_path = forms.pick_file(
    files_filter='Text files (*.tsv;*.txt;*.csv)|*.tsv;*.txt;*.csv|All files (*.*)|*.*'
)
if not in_path:
    log('User cancelled file pick')
    sys.exit()
log('Picked file: {}'.format(in_path))


# ------------------------------------------------------------------
# Read TSV — try several encodings so Excel-saved files work
# ------------------------------------------------------------------
encodings_to_try = ['utf-8-sig', 'utf-16', 'utf-16-le', 'cp1251', 'utf-8']

raw = None
used_encoding = None
last_error = None

for enc in encodings_to_try:
    try:
        with codecs.open(in_path, 'r', encoding=enc) as f:
            raw = f.read()
        # Sanity check: file should contain a tab (it's a TSV)
        if '\t' in raw:
            used_encoding = enc
            break
    except Exception as ex:
        last_error = ex
        continue

if raw is None or used_encoding is None:
    log('Read failed: ' + str(last_error))
    forms.alert(
        'Cannot read file with any supported encoding.\n'
        'Tried: UTF-8, UTF-16, Windows-1251.\n\n'
        'Last error: {}'.format(str(last_error) if last_error else '—'),
        title='Read error', exitscript=True
    )

log('File read OK with encoding: {}; raw length: {}'.format(used_encoding, len(raw)))

try:
    lines = raw.splitlines()
    log('Splitlines OK: {} lines'.format(len(lines)))
except Exception as ex:
    log('Splitlines err: ' + str(ex))
    forms.alert('Splitlines error: ' + str(ex), exitscript=True)

if len(lines) < 2:
    log('File too short')
    forms.alert('File is empty or has no data rows.',
                title='Empty file', exitscript=True)

# Log first/last raw lines (helps spot encoding artefacts)
try:
    first_line_repr = repr(lines[0][:200])
    log('Header line repr: ' + first_line_repr)
except Exception as ex:
    log('Header repr err: ' + str(ex))


# ------------------------------------------------------------------
# Parse: skip header, collect rows with non-empty NewName
# ------------------------------------------------------------------
log('Starting parse loop...')

to_apply = []   # list of (cat, element_id_int, current, new)
parse_errors = 0
parse_loop_errors = 0

for line_idx, ln in enumerate(lines[1:]):
    try:
        if not ln.strip():
            continue
        parts = ln.split('\t')
        if len(parts) < 4:
            parse_errors += 1
            continue

        cat     = parts[0].strip()
        id_str  = parts[1].strip()
        current = parts[2]
        new     = parts[3].strip()

        if not new:
            continue
        if new == current:
            continue

        try:
            eid = int(id_str)
        except ValueError:
            parse_errors += 1
            continue

        to_apply.append((cat, eid, current, new))
    except Exception as ex:
        parse_loop_errors += 1
        if parse_loop_errors <= 3:
            log('  parse line {} err: {}'.format(line_idx, str(ex)))


log('Parse loop done. Renames={} parse_errors={} loop_errors={}'.format(
    len(to_apply), parse_errors, parse_loop_errors))

# Log first 20 entries for diagnostics — fully wrapped, can't crash
log('Logging first 20 entries...')
for i in range(min(20, len(to_apply))):
    try:
        t = to_apply[i]
        # Use safe repr — avoids any encoding mismatch
        log(u'  [{0}] cat={1} id={2} cur={3} new={4}'.format(
            i, repr(t[0]), t[1], repr(t[2]), repr(t[3])
        ))
    except Exception as ex:
        try:
            log('  [{}] <log error: {}>'.format(i, str(ex)))
        except Exception:
            pass
log('Diagnostic logging done')

if not to_apply:
    forms.alert(
        'No translations to apply (NewName column is empty for all rows '
        'or matches CurrentName).\n\n'
        'Parse errors: {}'.format(parse_errors),
        title='Nothing to do', exitscript=True
    )


# ------------------------------------------------------------------
# Confirm — minimal message, no preview (preview can crash WPF on weird unicode)
# ------------------------------------------------------------------
log('Showing confirmation dialog...')
try:
    confirm = forms.alert(
        'Apply {} renames?\nParse errors: {}'.format(len(to_apply), parse_errors),
        title='Apply translations', yes=True, no=True
    )
except Exception as ex:
    log('Confirm dialog err: ' + str(ex))
    confirm = False
log('User confirmed: {}'.format(confirm))
if not confirm:
    sys.exit()


# ------------------------------------------------------------------
# Forbidden chars in Revit names
# ------------------------------------------------------------------
FORBIDDEN_CHARS = set(['\\', ':', '{', '}', '[', ']', '|', ';',
                       '<', '>', '?', '`', '~'])


def has_forbidden(name):
    return any(c in FORBIDDEN_CHARS for c in name)


# ------------------------------------------------------------------
# Active view id — skip the element currently displayed (renaming
# the active view template / view itself sometimes crashes Revit)
# ------------------------------------------------------------------
try:
    active_view_id = uidoc.ActiveView.Id.IntegerValue
except Exception:
    active_view_id = -1


# ------------------------------------------------------------------
# Apply renames — ONE Transaction with SubTransaction per element
# (no ProgressBar — it has been seen to interfere with transactions)
# ------------------------------------------------------------------
results = []

log('Active view id captured: {}'.format(active_view_id))
log('Starting main transaction...')

main_tx = Transaction(doc, 'Apply translations')
try:
    main_tx.Start()
    log('Main transaction started')
except Exception as ex:
    log('FATAL: cannot start transaction: ' + str(ex))
    forms.alert('Cannot start transaction:\n' + str(ex),
                title='Error', exitscript=True)

try:
    for i, (cat, eid, current, new) in enumerate(to_apply):
        log('--- iter {}/{}  cat={}  id={}'.format(i + 1, len(to_apply), cat, eid))

        # ---- pre-checks ----
        if not new:
            results.append([cat, eid, current, new, 'Skip: empty new name'])
            log('  skip: empty new')
            continue

        if has_forbidden(new):
            results.append([cat, eid, current, new,
                            'Skip: forbidden chars in new name'])
            log('  skip: forbidden chars')
            continue

        if eid == active_view_id:
            results.append([cat, eid, current, new,
                            'Skip: element is the active view'])
            log('  skip: active view')
            continue

        # ---- locate element ----
        log('  locating element...')
        try:
            elem = doc.GetElement(ElementId(eid))
        except Exception as ex:
            results.append([cat, eid, current, new, 'GetElement error: ' + str(ex)])
            log('  GetElement err: ' + str(ex))
            continue

        if elem is None:
            results.append([cat, eid, current, new, 'Element not found'])
            log('  not found')
            continue

        log('  element type: {}'.format(elem.GetType().Name))

        # ---- read current name ----
        try:
            old = elem.Name
        except Exception as ex:
            log('  read Name err: ' + str(ex))
            old = current

        if old == new:
            results.append([cat, eid, old, new, 'Skip: already named'])
            log('  skip: already named')
            continue

        # ---- isolated sub-transaction ----
        log('  starting sub-transaction...')
        sub = SubTransaction(doc)
        try:
            sub.Start()
            try:
                new_str = new.encode('utf-8') if isinstance(new, unicode) else new
            except Exception:
                new_str = '<unprintable>'
            log('  set Name -> {}'.format(new_str))
            elem.Name = new
            sub.Commit()
            results.append([cat, eid, old, new, 'OK'])
            log('  OK')
        except Exception as ex:
            try:
                sub.RollBack()
            except Exception:
                pass
            results.append([cat, eid, old, new, 'Set error: ' + str(ex)])
            log('  set err: ' + str(ex))

    log('Loop finished; committing main transaction...')
    main_tx.Commit()
    log('Main transaction committed OK')

except Exception as ex:
    log('FATAL outer err: ' + str(ex))
    try:
        main_tx.RollBack()
        log('Main transaction rolled back')
    except Exception as ex2:
        log('Rollback err: ' + str(ex2))
    forms.alert('Fatal error: {}\nLog: {}'.format(str(ex), log_path),
                title='Error', exitscript=True)


log('Done. OK={}, Errors={}'.format(
    sum(1 for r in results if r[4] == 'OK'),
    sum(1 for r in results if r[4] != 'OK')
))
log_f.close()


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------
ok  = sum(1 for r in results if r[4] == 'OK')
err = len(results) - ok

output.print_md('## Apply Translations — Report')
output.print_md(
    '**Encoding:** {}  |  **Renamed:** {}  |  **Errors:** {}  |  **Parse errors:** {}'.format(
        used_encoding, ok, err, parse_errors
    )
)

output.print_table(
    table_data=results,
    columns=['Category', 'Id', 'Old Name', 'New Name', 'Status']
)

output.print_md('### Crash log')
output.print_md('Detailed log written to: `{}`'.format(log_path))

forms.alert(
    '{} elements renamed.\n{} errors/skipped.\n\nLog file:\n{}'.format(
        ok, err, log_path
    ),
    title='Done'
)
