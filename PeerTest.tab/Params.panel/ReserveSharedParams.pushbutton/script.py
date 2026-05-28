# -*- coding: utf-8 -*-
__title__  = 'Reserve\nShared Params'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-27
Description:
    Scans a folder of .rfa families, collects every shared parameter
    (GUID, group, Instance/Type, family category), and registers them
    in the CURRENT empty template as project parameters with English
    names from the attached SPF (matched by GUID).

    After running the script, just load the families into this template —
    their shared parameters will merge with the project parameters by GUID
    and display the English names.
How-To:
    1. Open a CLEAN empty template (no shared params yet).
    2. Attach the new English SPF (Manage -> Shared Parameters).
    3. Run the script.
    4. Pick the folder with .rfa families (subfolders supported).
    5. Confirm the summary.
    6. Load families into the template.
'''

import os
import sys
import traceback
from System import Enum
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Category,
    OpenOptions, ModelPathUtils, Transaction
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# 0. Sanity checks
# ------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert('Run this script in a PROJECT/TEMPLATE, not in a family.',
                title='Wrong document type', exitscript=True)


# ------------------------------------------------------------------
# 1. Build SPF index by GUID
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert('No Shared Parameter File attached.',
                title='SPF not found', exitscript=True)

spf_by_guid = {}
for grp in def_file.Groups:
    for d in grp.Definitions:
        spf_by_guid[str(d.GUID)] = d


# ------------------------------------------------------------------
# 2. Pick folder with families
# ------------------------------------------------------------------
src_folder = forms.pick_folder(title='Select folder with .rfa families')
if not src_folder:
    sys.exit()

rfa_files = []
for root, dirs, files in os.walk(src_folder):
    for f in files:
        if f.lower().endswith('.rfa'):
            rfa_files.append(os.path.join(root, f))

if not rfa_files:
    forms.alert('No .rfa files in:\n' + src_folder,
                title='Empty folder', exitscript=True)


# ------------------------------------------------------------------
# 3. Scan all .rfa: collect (guid -> {bics, is_instance, group, old_name})
# ------------------------------------------------------------------
agg = {}
# agg[guid] = {
#   'old_name':    str   (first encountered),
#   'group':       BuiltInParameterGroup (first encountered),
#   'is_instance': bool  (first encountered, conflicts logged),
#   'bics':        set of BuiltInCategory enum values (negative ints),
#   'families':    list of file names where seen,
#   'conflicts':   list of strings,
# }

scan_errors = []

with forms.ProgressBar(title='Scanning families... ({value}/{max_value})',
                       cancellable=True, step=1) as pb:
    pb.max_value = len(rfa_files)

    for i, rfa_path in enumerate(rfa_files):
        if pb.cancelled:
            sys.exit()
        pb.update_progress(i + 1, len(rfa_files))

        fam_doc = None
        try:
            mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(rfa_path)
            fam_doc = app.OpenDocumentFile(mp, OpenOptions())

            owner = fam_doc.OwnerFamily
            if owner is None or owner.FamilyCategory is None:
                fam_doc.Close(False)
                continue

            fam_cat_id = owner.FamilyCategory.Id.IntegerValue

            fm = fam_doc.FamilyManager
            for fp in fm.Parameters:
                if not fp.IsShared:
                    continue

                guid = str(fp.GUID)
                old_name    = fp.Definition.Name
                group       = fp.Definition.ParameterGroup
                is_instance = fp.IsInstance

                if guid not in agg:
                    agg[guid] = {
                        'old_name':    old_name,
                        'group':       group,
                        'is_instance': is_instance,
                        'bics':        set(),
                        'families':    [],
                        'conflicts':   [],
                    }

                rec = agg[guid]
                rec['bics'].add(fam_cat_id)
                rec['families'].append(os.path.basename(rfa_path))

                if rec['is_instance'] != is_instance:
                    rec['conflicts'].append(
                        'Instance/Type mismatch in ' + os.path.basename(rfa_path)
                    )
                if rec['group'] != group:
                    rec['conflicts'].append(
                        'Group mismatch in ' + os.path.basename(rfa_path)
                    )

            fam_doc.Close(False)
            fam_doc = None

        except Exception as ex:
            if fam_doc is not None:
                try:
                    fam_doc.Close(False)
                except Exception:
                    pass
            scan_errors.append('{}: {}'.format(os.path.basename(rfa_path), str(ex)))


# ------------------------------------------------------------------
# 4. Confirmation
# ------------------------------------------------------------------
if not agg:
    forms.alert('No shared parameters found in the scanned families.',
                title='Nothing to reserve', exitscript=True)

confirm = forms.alert(
    'Scanned {} families.\n'
    'Found {} unique shared parameters.\n'
    '{} scan errors.\n\n'
    'Register these as project parameters in the current template?'.format(
        len(rfa_files), len(agg), len(scan_errors)
    ),
    title='Reserve shared params', yes=True, no=True
)
if not confirm:
    sys.exit()


# ------------------------------------------------------------------
# 5. Build project Category lookup + insert bindings
# ------------------------------------------------------------------
proj_cat_by_intid = {}
for c in doc.Settings.Categories:
    try:
        if c.AllowsBoundParameters:
            proj_cat_by_intid[c.Id.IntegerValue] = c
    except Exception:
        pass


report_rows = []   # [old_name, new_name, guid, group, kind, categories, status]

with Transaction(doc, 'Reserve shared parameters') as t:
    t.Start()

    for guid, rec in agg.items():
        new_ext_def = spf_by_guid.get(guid)
        if new_ext_def is None:
            report_rows.append([
                rec['old_name'], '—', guid,
                str(rec['group']),
                'Instance' if rec['is_instance'] else 'Type',
                str(len(rec['bics'])),
                'GUID not found in SPF'
            ])
            continue

        # Build CategorySet from collected family categories
        cat_set = app.Create.NewCategorySet()
        cats_added  = 0
        cats_missed = 0
        for bic_int in rec['bics']:
            cat = proj_cat_by_intid.get(bic_int)
            if cat is None:
                cats_missed += 1
                continue
            try:
                cat_set.Insert(cat)
                cats_added += 1
            except Exception:
                cats_missed += 1

        if cats_added == 0:
            report_rows.append([
                rec['old_name'], new_ext_def.Name, guid,
                str(rec['group']),
                'Instance' if rec['is_instance'] else 'Type',
                '0',
                'No usable categories'
            ])
            continue

        try:
            if rec['is_instance']:
                new_binding = app.Create.NewInstanceBinding(cat_set)
            else:
                new_binding = app.Create.NewTypeBinding(cat_set)

            ok = doc.ParameterBindings.Insert(
                new_ext_def, new_binding, rec['group']
            )
            if not ok:
                ok = doc.ParameterBindings.ReInsert(
                    new_ext_def, new_binding, rec['group']
                )

            status = 'OK' if ok else 'Insert returned False'
            if rec['conflicts']:
                status += ' (conflicts: {})'.format(len(rec['conflicts']))

            report_rows.append([
                rec['old_name'], new_ext_def.Name, guid,
                str(rec['group']),
                'Instance' if rec['is_instance'] else 'Type',
                '{} ({} skipped)'.format(cats_added, cats_missed) if cats_missed else str(cats_added),
                status
            ])
        except Exception as ex:
            report_rows.append([
                rec['old_name'], new_ext_def.Name, guid,
                str(rec['group']),
                'Instance' if rec['is_instance'] else 'Type',
                str(cats_added),
                'Insert error: ' + str(ex)
            ])

    t.Commit()


# ------------------------------------------------------------------
# 6. Report
# ------------------------------------------------------------------
ok_count  = sum(1 for r in report_rows if r[6].startswith('OK'))
err_count = len(report_rows) - ok_count

output.print_md('## Reserve Shared Params — Report')
output.print_md(
    '**Scanned families:** {}  |  '
    '**Unique shared params:** {}  |  '
    '**Registered OK:** {}  |  '
    '**Errors/Skipped:** {}  |  '
    '**Scan errors:** {}'.format(
        len(rfa_files), len(agg), ok_count, err_count, len(scan_errors)
    )
)

output.print_table(
    table_data=report_rows,
    columns=['Old name (in family)', 'New name (from SPF)', 'GUID',
             'Group', 'Kind', 'Categories', 'Status']
)

if scan_errors:
    output.print_md('### Scan errors')
    for e in scan_errors[:20]:
        output.print_md('- ' + e)

forms.alert(
    '{} parameters registered as project parameters.\n'
    '{} errors/skipped. See report for details.\n\n'
    'Now you can load families into this template.'.format(ok_count, err_count),
    title='Done'
)
