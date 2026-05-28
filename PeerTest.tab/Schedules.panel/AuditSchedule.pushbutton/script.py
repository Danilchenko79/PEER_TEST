# -*- coding: utf-8 -*-
"""Pick one or more schedules → get a detailed parameter report.

For each schedule field shows:
- column header / field name
- field kind (Instance / Calculated / CombinedParameter / etc.)
- bound parameter name (the live name in this project)
- GUID for shared parameters (lets you cross-check with another project)
- "is broken?" flag if the parameter is missing or unbound

Also lists parameters used in Sorting/Grouping and in the schedule's Filter.

Output goes to pyRevit window AND to a CSV in %TEMP% so you can paste it
side-by-side with the same dump from another project.
"""

import os
import codecs
import csv
import datetime

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ViewSchedule,
    SharedParameterElement,
    ScheduleFieldType,
    Category,
    BuiltInParameter,
)
from pyrevit import revit, script, forms

doc = revit.doc
out = script.get_output()
out.close_others()


# ---------- helpers ----------
def _safe(getter, default=''):
    try:
        v = getter()
        return v if v is not None else default
    except Exception:
        return default


def _shared_param_by_guid(guid_str):
    for sp in FilteredElementCollector(doc).OfClass(SharedParameterElement):
        if str(sp.GuidValue) == guid_str:
            return sp
    return None


def _field_kind(field):
    try:
        ft = field.FieldType
    except Exception:
        return '?'
    try:
        return str(ft)
    except Exception:
        return '?'


def _spec_label(definition):
    try:
        from Autodesk.Revit.DB import LabelUtils
        return LabelUtils.GetLabelForSpec(definition.GetDataType())
    except Exception:
        try:
            return str(definition.ParameterType)
        except Exception:
            return ''


# ---------- pick schedules ----------
all_sch = [s for s in FilteredElementCollector(doc).OfClass(ViewSchedule)
           if not s.IsTemplate]
if not all_sch:
    forms.alert('No schedules in this project.', exitscript=True)

picked = forms.SelectFromList.show(
    sorted(all_sch, key=lambda s: s.Name),
    name_attr='Name',
    title='Pick schedule(s) to audit',
    multiselect=True,
)
if not picked:
    script.exit()


# ---------- collect ----------
csv_rows = []  # list of dicts for CSV
md_sections = []  # markdown chunks per schedule


def _add_csv(schedule_name, section, **kw):
    row = {
        'schedule': schedule_name,
        'section': section,
        'idx': '',
        'header': '',
        'field_name': '',
        'kind': '',
        'param_name': '',
        'guid': '',
        'spec': '',
        'group': '',
        'is_calculated': '',
        'is_combined': '',
        'is_broken': '',
        'note': '',
    }
    row.update(kw)
    csv_rows.append(row)


for sch in picked:
    sd = sch.Definition
    cat_name = ''
    try:
        cat_name = Category.GetCategory(doc, sd.CategoryId).Name
    except Exception:
        pass

    md = ['## %s' % sch.Name, '*category:* `%s`' % cat_name, '', '### Fields']
    md.append('| # | Header | Kind | Param name | GUID | Spec | Group | Flags |')
    md.append('|---:|---|---|---|---|---|---|---|')

    n = sd.GetFieldCount()
    for i in range(n):
        try:
            fld = sd.GetField(i)
        except Exception as ex:
            md.append('| %d | <read error> | | | | | | %s |' % (i, ex))
            _add_csv(sch.Name, 'field', idx=str(i), is_broken='True', note=str(ex))
            continue

        header = _safe(lambda: fld.ColumnHeading) or ''
        fname = _safe(lambda: fld.GetName()) or ''
        kind = _field_kind(fld)

        # is calculated
        is_calc = False
        try:
            is_calc = bool(fld.IsCalculatedField)
        except Exception:
            pass

        # is combined parameter (Revit 2022+)
        is_combo = False
        try:
            is_combo = bool(fld.IsCombinedParameterField)
        except Exception:
            pass

        # try to find the underlying parameter
        pname = ''
        guid = ''
        spec = ''
        group = ''
        flags = []

        if is_calc:
            flags.append('CALCULATED')
            pname = '<formula: %s>' % _safe(lambda: fld.Formula)
        elif is_combo:
            flags.append('COMBINED')
            pname = '<combined parameter>'
        else:
            # regular parameter
            try:
                pid = fld.ParameterId
                if pid is not None and pid.IntegerValue > 0:
                    pelem = doc.GetElement(pid)
                    if pelem is not None:
                        try:
                            d = pelem.GetDefinition()
                            pname = d.Name
                            spec = _spec_label(d)
                            try:
                                from Autodesk.Revit.DB import LabelUtils
                                group = LabelUtils.GetLabelForGroup(d.GetGroupTypeId())
                            except Exception:
                                pass
                        except Exception:
                            pname = '<no definition>'
                        if isinstance(pelem, SharedParameterElement):
                            guid = str(pelem.GuidValue)
                            flags.append('SHARED')
                        else:
                            flags.append('PROJECT')
                    else:
                        flags.append('BROKEN_REF')
                elif pid is not None and pid.IntegerValue < 0:
                    flags.append('BUILTIN')
                    pname = '<BIP %d>' % pid.IntegerValue
            except Exception as ex:
                flags.append('READ_ERROR')
                pname = str(ex)

        if not pname:
            flags.append('EMPTY_PARAM_REF')

        # mismatch: header overridden vs field name
        if header and fname and header.strip() != fname.strip():
            flags.append('HEADER_OVERRIDE')

        md.append('| %d | %s | %s | %s | %s | %s | %s | %s |' % (
            i, header, kind, pname, ('`%s`' % guid) if guid else '',
            spec, group, ', '.join(flags),
        ))

        _add_csv(sch.Name, 'field',
                 idx=str(i), header=header, field_name=fname,
                 kind=kind, param_name=pname, guid=guid,
                 spec=spec, group=group,
                 is_calculated=str(is_calc),
                 is_combined=str(is_combo),
                 is_broken='True' if ('BROKEN_REF' in flags or 'EMPTY_PARAM_REF' in flags or 'READ_ERROR' in flags) else 'False',
                 note=', '.join(flags))

    # Sorting / grouping
    md.append('')
    md.append('### Sort / Group')
    try:
        sg_count = sd.GetSortGroupFieldCount()
        if sg_count == 0:
            md.append('_none_')
        else:
            md.append('| # | Field index | Field name | Sort order | Header? | Footer? |')
            md.append('|---:|---:|---|---|---|---|')
            for j in range(sg_count):
                sg = sd.GetSortGroupField(j)
                # find field name
                try:
                    fld = sd.GetField(sg.FieldId)
                    fname = fld.GetName()
                except Exception:
                    fname = '<broken>'
                md.append('| %d | %s | %s | %s | %s | %s |' % (
                    j, sg.FieldId.IntegerValue, fname, sg.SortOrder,
                    sg.ShowHeader, sg.ShowFooter))
                _add_csv(sch.Name, 'sort_group', idx=str(j),
                         field_name=fname,
                         note='SortOrder=%s' % sg.SortOrder)
    except Exception as ex:
        md.append('_error reading sort/group: %s_' % ex)

    # Filters
    md.append('')
    md.append('### Filter rules')
    try:
        fc = sd.GetFilterCount()
        if fc == 0:
            md.append('_none_')
        else:
            md.append('| # | Field name | Filter type | Value |')
            md.append('|---:|---|---|---|')
            for j in range(fc):
                f = sd.GetFilter(j)
                try:
                    fld = sd.GetField(f.FieldId)
                    fname = fld.GetName()
                except Exception:
                    fname = '<broken>'
                ftype = str(_safe(lambda: f.FilterType))
                value = ''
                for getter in (lambda: f.GetStringValue(),
                               lambda: f.GetDoubleValue(),
                               lambda: f.GetIntegerValue(),
                               lambda: f.GetElementIdValue().IntegerValue):
                    try:
                        v = getter()
                        if v is not None and v != '':
                            value = unicode(v)
                            break
                    except Exception:
                        continue
                md.append('| %d | %s | %s | %s |' % (j, fname, ftype, value))
                _add_csv(sch.Name, 'filter', idx=str(j),
                         field_name=fname,
                         note='%s = %s' % (ftype, value))
    except Exception as ex:
        md.append('_error reading filters: %s_' % ex)

    md_sections.append('\n'.join(md))


# ---------- print ----------
out.print_md('# Schedule audit')
out.print_md('Project: **%s**' % doc.Title)
out.print_md('Schedules audited: **%d**' % len(picked))
for s in md_sections:
    out.print_md('---')
    out.print_md(s)


# ---------- CSV ----------
safe_title = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in doc.Title)
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
out_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(
    out_dir,
    'schedule_audit_%s_%s.csv' % (safe_title, ts)
)

with codecs.open(out_path, 'w', encoding='utf-8-sig') as fh:
    writer = csv.writer(fh)
    cols = ['schedule', 'section', 'idx', 'header', 'field_name',
            'kind', 'param_name', 'guid', 'spec', 'group',
            'is_calculated', 'is_combined', 'is_broken', 'note']
    writer.writerow(cols)
    for r in csv_rows:
        writer.writerow([
            r[c].encode('utf-8') if isinstance(r[c], unicode) else str(r[c])
            for c in cols
        ])

out.print_md('---')
out.print_md('CSV: `%s`' % out_path)
forms.alert('Saved to:\n%s' % out_path, title='Schedule audit')
