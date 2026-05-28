# -*- coding: utf-8 -*-
__title__  = 'Rename\nFamily Params'
__author__ = 'Dima'
__doc__    = '''Version = 3.0
Date      = 2026-04-27
Description:
    Batch-renames shared parameters inside .rfa family files.
    Removes old shared params and re-adds them from the new SPF (by GUID),
    while preserving:
      - formulas of shared params (with name translation in the formula text)
      - formulas of regular family params that reference shared param names
      - Dimension.FamilyLabel links (size labels)
      - associations to nested family instance parameters
How-To:
    1. Attach the new English SPF via Manage -> Shared Parameters.
    2. Run the script.
    3. Pick the SOURCE folder (.rfa files; subfolders supported).
    4. Pick the DESTINATION folder (folder structure is mirrored).
    5. Review the report table.
'''

import os
import sys
from Autodesk.Revit.DB import (
    FilteredElementCollector, SharedParameterElement,
    OpenOptions, SaveAsOptions, ModelPathUtils,
    Transaction, Dimension, FamilyInstance
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# 1. Build GUID -> ExternalDefinition index from attached SPF
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert(
        'No Shared Parameter File is attached.\n'
        'Attach it via Manage -> Shared Parameters.',
        title='SPF not found', exitscript=True
    )

spf_by_guid = {}
for grp in def_file.Groups:
    for d in grp.Definitions:
        spf_by_guid[str(d.GUID)] = d


# ------------------------------------------------------------------
# 2. Pick folders
# ------------------------------------------------------------------
src_folder = forms.pick_folder(title='Select SOURCE folder with .rfa files')
if not src_folder:
    sys.exit()

dst_folder = forms.pick_folder(title='Select DESTINATION folder for processed files')
if not dst_folder:
    sys.exit()

# Recursive scan — collect (abs_path, relative_path) for every .rfa
rfa_files = []
for root, dirs, files in os.walk(src_folder):
    for f in files:
        if f.lower().endswith('.rfa'):
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, src_folder)
            rfa_files.append((abs_path, rel_path))

if not rfa_files:
    forms.alert('No .rfa files found (including subfolders) in:\n' + src_folder,
                title='Empty folder', exitscript=True)

confirm = forms.alert(
    'Found {} .rfa files (including subfolders).\n'
    'Source:      {}\n'
    'Destination: {}\n\n'
    'Folder structure will be preserved.\nProceed?'.format(
        len(rfa_files), src_folder, dst_folder
    ),
    title='Confirm', yes=True, no=True
)
if not confirm:
    sys.exit()


# ------------------------------------------------------------------
# 3. Helper: process one family document
# ------------------------------------------------------------------
def _translate(formula_str, name_map):
    """Replace old parameter names with new ones in a formula string.
    Sort by length DESC so 'Длина_Сваи' is replaced before 'Длина'."""
    if not formula_str:
        return formula_str
    result = formula_str
    for old in sorted(name_map.keys(), key=lambda x: -len(x)):
        result = result.replace(old, name_map[old])
    return result


def process_family_doc(fam_doc, spf_index):
    """
    Renames all shared FamilyParameters in fam_doc by:
      1) snapshotting formulas, dimension labels, nested-family associations
      2) clearing dependencies → removing old shared params
      3) adding new shared params from SPF (by GUID)
      4) restoring formulas (translated), labels, associations
    Returns list of result dicts: {old_name, new_name, status}
    """
    fm = fam_doc.FamilyManager
    results = []

    # ---------- STEP 1: snapshot shared params ----------
    shared_data = []
    for fp in fm.Parameters:
        if not fp.IsShared:
            continue
        new_ext_def = spf_index.get(str(fp.GUID))
        shared_data.append({
            'fp':          fp,
            'fp_id':       fp.Id,
            'guid':        str(fp.GUID),
            'old_name':    fp.Definition.Name,
            'new_ext_def': new_ext_def,
            'new_name':    new_ext_def.Name if new_ext_def is not None else None,
            'group':       fp.Definition.ParameterGroup,
            'is_instance': fp.IsInstance,
            'formula':     fp.Formula,   # may be None
        })

    if not shared_data:
        return results

    # Name map: only for params that will actually change name
    name_map = {}
    for item in shared_data:
        if item['new_name'] and item['new_name'] != item['old_name']:
            name_map[item['old_name']] = item['new_name']

    # ---------- STEP 2: snapshot non-shared family params with referencing formulas ----------
    non_shared_to_retranslate = []
    for fp in fm.Parameters:
        if fp.IsShared:
            continue
        formula = fp.Formula
        if not formula:
            continue
        if any(old_name in formula for old_name in name_map):
            non_shared_to_retranslate.append({
                'fp':      fp,
                'formula': formula,
                'name':    fp.Definition.Name,
            })

    # ---------- STEP 3: snapshot dimension labels ----------
    shared_id_to_guid = {}
    for item in shared_data:
        shared_id_to_guid[item['fp_id'].IntegerValue] = item['guid']

    dim_links = []   # list of (dim_id, guid)
    try:
        for dim in FilteredElementCollector(fam_doc).OfClass(Dimension):
            try:
                label = dim.FamilyLabel
            except Exception:
                label = None
            if label is None:
                continue
            key = label.Id.IntegerValue
            if key in shared_id_to_guid:
                dim_links.append((dim.Id, shared_id_to_guid[key]))
    except Exception:
        pass

    # ---------- STEP 4: snapshot nested family parameter associations ----------
    nested_links = []   # list of (instance_id, inst_param_name, guid)
    try:
        for fi in FilteredElementCollector(fam_doc).OfClass(FamilyInstance):
            for inst_param in fi.Parameters:
                try:
                    host_fp = fm.GetAssociatedFamilyParameter(inst_param)
                except Exception:
                    host_fp = None
                if host_fp is None:
                    continue
                key = host_fp.Id.IntegerValue
                if key in shared_id_to_guid:
                    nested_links.append((
                        fi.Id,
                        inst_param.Definition.Name,
                        shared_id_to_guid[key]
                    ))
    except Exception:
        pass

    # ---------- STEP 5: transaction ----------
    with Transaction(fam_doc, 'Rename shared params') as t:
        t.Start()

        # 5a. Clear formulas on shared params (break dependencies)
        for item in shared_data:
            if item['formula']:
                try:
                    fm.SetFormula(item['fp'], None)
                except Exception:
                    pass

        # 5b. Clear formulas on non-shared family params that reference old names
        for nsd in non_shared_to_retranslate:
            try:
                fm.SetFormula(nsd['fp'], None)
            except Exception:
                pass

        # 5c. Unset dimension labels
        for dim_id, _guid in dim_links:
            try:
                dim = fam_doc.GetElement(dim_id)
                dim.FamilyLabel = None
            except Exception:
                pass

        # 5d. Remove old shared params
        for item in shared_data:
            try:
                fm.RemoveParameter(item['fp'])
            except Exception as ex:
                item['remove_error'] = str(ex)

        # 5e. Add new shared params from SPF
        new_fp_by_guid = {}
        for item in shared_data:
            if 'remove_error' in item:
                results.append({
                    'old_name': item['old_name'],
                    'new_name': item['new_name'] or '—',
                    'status':   'Remove failed: ' + item['remove_error']
                })
                continue

            if item['new_ext_def'] is None:
                results.append({
                    'old_name': item['old_name'],
                    'new_name': '—',
                    'status':   'GUID not found in SPF'
                })
                continue

            try:
                new_fp = fm.AddParameter(
                    item['new_ext_def'], item['group'], item['is_instance']
                )
                new_fp_by_guid[item['guid']] = new_fp
                results.append({
                    'old_name': item['old_name'],
                    'new_name': item['new_name'],
                    'status':   'OK'
                })
            except Exception as ex:
                results.append({
                    'old_name': item['old_name'],
                    'new_name': item['new_name'] or '—',
                    'status':   'AddParameter error: ' + str(ex)
                })

        # 5f. Restore formulas on shared params (translated)
        for item in shared_data:
            if not item['formula']:
                continue
            new_fp = new_fp_by_guid.get(item['guid'])
            if new_fp is None:
                continue
            try:
                fm.SetFormula(new_fp, _translate(item['formula'], name_map))
            except Exception:
                pass

        # 5g. Restore formulas on non-shared family params (translated)
        for nsd in non_shared_to_retranslate:
            try:
                fm.SetFormula(nsd['fp'], _translate(nsd['formula'], name_map))
            except Exception:
                pass

        # 5h. Re-link dimensions to new params
        for dim_id, guid in dim_links:
            new_fp = new_fp_by_guid.get(guid)
            if new_fp is None:
                continue
            try:
                dim = fam_doc.GetElement(dim_id)
                dim.FamilyLabel = new_fp
            except Exception:
                pass

        # 5i. Re-associate nested family parameters
        for fi_id, inst_param_name, guid in nested_links:
            new_fp = new_fp_by_guid.get(guid)
            if new_fp is None:
                continue
            try:
                fi = fam_doc.GetElement(fi_id)
                inst_param = fi.LookupParameter(inst_param_name)
                if inst_param is not None:
                    fm.AssociateElementParameterToFamilyParameter(inst_param, new_fp)
            except Exception:
                pass

        t.Commit()

    return results


# ------------------------------------------------------------------
# 4. Process every .rfa file
# ------------------------------------------------------------------
save_opts = SaveAsOptions()
save_opts.OverwriteExistingFile = True

all_rows   = []   # for final report table
ok_files   = 0
fail_files = 0

for rfa_path, rel_path in rfa_files:
    file_name = os.path.basename(rfa_path)
    dst_path  = os.path.join(dst_folder, rel_path)

    # Ensure destination subfolder exists
    dst_dir = os.path.dirname(dst_path)
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    fam_doc = None
    try:
        model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(rfa_path)
        open_opts  = OpenOptions()
        fam_doc    = app.OpenDocumentFile(model_path, open_opts)

        param_results = process_family_doc(fam_doc, spf_by_guid)

        fam_doc.SaveAs(dst_path, save_opts)
        fam_doc.Close(False)
        fam_doc = None

        # Use relative path in report so subfolder is visible
        display_name = rel_path
        if not param_results:
            all_rows.append([display_name, '—', '—', 'No shared params'])
        else:
            for r in param_results:
                all_rows.append([display_name, r['old_name'], r['new_name'], r['status']])

        ok_files += 1

    except Exception as ex:
        if fam_doc is not None:
            try:
                fam_doc.Close(False)
            except Exception:
                pass
        all_rows.append([rel_path, '—', '—', 'FILE ERROR: ' + str(ex)])
        fail_files += 1


# ------------------------------------------------------------------
# 5. Report
# ------------------------------------------------------------------
ok_params      = sum(1 for r in all_rows if r[3].startswith('OK'))
skipped_params = sum(1 for r in all_rows if r[3].startswith('Skipped')
                                          or r[3] == 'No shared params')
err_params     = len(all_rows) - ok_params - skipped_params

output.print_md('## ReCreate Family Params — Report')
output.print_md(
    '**Files:** {} processed, {} errors  |  '
    '**Params:** {} OK, {} errors'.format(
        ok_files, fail_files, ok_params, err_params
    )
)

output.print_table(
    table_data=all_rows,
    columns=['Family file', 'Old param name', 'New param name', 'Status']
)

if fail_files == 0 and err_params == 0:
    forms.alert(
        '{} families processed.\n{} shared parameters recreated.'.format(
            ok_files, ok_params
        ),
        title='Done'
    )
else:
    forms.alert(
        '{} files OK, {} errors.\n{} param errors.\nSee report for details.'.format(
            ok_files, fail_files, err_params
        ),
        title='Partial Success'
    )
