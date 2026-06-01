# -*- coding: utf-8 -*-
"""Audit ADSK BIM2B template after migration to PR_* shared parameters.

Collects everything still referencing the old Russian ADSK_* parameters or the
old Russian rebar prefixes (В/Н/в/к/дз/зд/мп_), and dumps a CSV report to
%TEMP%\\peer_audit_report.csv plus a summary in the pyRevit output window.

Run this on an open .rte template (or a project based on it).
"""

import os
import re
import csv
import codecs
from collections import defaultdict

from pyrevit import revit, script
from Autodesk.Revit.DB import (
    Element,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    ParameterFilterElement,
    ElementParameterFilter,
    LogicalAndFilter,
    LogicalOrFilter,
    FilterRule,
    FilterStringRule,
    FilterDoubleRule,
    FilterIntegerRule,
    FilterElementIdRule,
    View,
    ViewSchedule,
    Family,
    FamilyManager,
    Material,
    Category,
)


def _name_of(elem):
    """Robust element-name reader. RebarBarType etc. don't expose .Name in IronPython."""
    if elem is None:
        return ''
    try:
        n = Element.Name.GetValue(elem)
        if n:
            return n
    except Exception:
        pass
    for bip in (
        BuiltInParameter.SYMBOL_NAME_PARAM,
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
        BuiltInParameter.DATUM_TEXT,
    ):
        try:
            p = elem.get_Parameter(bip)
            if p is not None:
                v = p.AsString()
                if v:
                    return v
        except Exception:
            continue
    try:
        return elem.Name
    except Exception:
        return ''

doc = revit.doc
output = script.get_output()

CYRILLIC_RE = re.compile(u'[Ѐ-ӿ]')
RU_PREFIXES = (u'В_', u'Н_', u'в_', u'к_', u'д_', u'дз_', u'зд_', u'мп_')

rows = []  # (section, name, detail, flags)


def has_cyrillic(s):
    if s is None:
        return False
    try:
        return bool(CYRILLIC_RE.search(s))
    except Exception:
        return False


def starts_with_ru_prefix(name):
    if not name:
        return False
    for p in RU_PREFIXES:
        if name.startswith(p):
            return True
    return False


def add(section, name, detail='', flags=''):
    rows.append((section, name or '', detail or '', flags or ''))


# ---------------------------------------------------------------- Section 1: Rebar types
def audit_rebar_types():
    cats = [
        (BuiltInCategory.OST_Rebar, 'Rebar'),
        (BuiltInCategory.OST_FabricAreas, 'FabricArea'),
        (BuiltInCategory.OST_FabricReinforcement, 'FabricSheet'),
        (BuiltInCategory.OST_PathRein, 'PathRein'),
        (BuiltInCategory.OST_AreaRein, 'AreaRein'),
    ]
    for bic, label in cats:
        try:
            types = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType().ToElements()
        except Exception as ex:
            add('1.RebarTypes', label, 'collect failed: %s' % ex, 'ERROR')
            continue
        for t in types:
            tname = _name_of(t) or '<no name>'
            comments = ''
            try:
                p = t.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS)
                if p:
                    comments = p.AsString() or ''
            except Exception:
                pass
            flags = []
            if has_cyrillic(tname):
                flags.append('CYRILLIC_NAME')
            if starts_with_ru_prefix(tname):
                flags.append('RU_PREFIX')
            if has_cyrillic(comments):
                flags.append('CYRILLIC_COMMENTS')
            add('1.RebarTypes', '%s : %s' % (label, tname), 'Comments="%s"' % comments, ','.join(flags))


# ---------------------------------------------------------------- Section 2: Tag families
def audit_tag_families():
    tag_cats = [
        BuiltInCategory.OST_RebarTags,
        BuiltInCategory.OST_MultiReferenceAnnotations,
        BuiltInCategory.OST_FabricAreaTags,
        BuiltInCategory.OST_FabricReinforcementTags,
        BuiltInCategory.OST_AreaReinTags,
        BuiltInCategory.OST_PathReinTags,
    ]
    seen = set()
    for bic in tag_cats:
        try:
            symbols = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType().ToElements()
        except Exception:
            continue
        for s in symbols:
            try:
                fam = s.Family
            except Exception:
                fam = None
            if fam is None:
                continue
            fid = fam.Id.IntegerValue
            if fid in seen:
                continue
            seen.add(fid)
            fname = fam.Name
            flags = []
            if has_cyrillic(fname):
                flags.append('CYRILLIC_FAMILY_NAME')
            param_refs = []
            try:
                fdoc = doc.EditFamily(fam)
                try:
                    fm = fdoc.FamilyManager
                    for p in fm.Parameters:
                        pname = p.Definition.Name
                        param_refs.append(pname)
                        if pname.startswith('ADSK_'):
                            flags.append('HAS_ADSK_PARAM')
                            break
                finally:
                    fdoc.Close(False)
            except Exception as ex:
                flags.append('EDIT_FAILED:%s' % type(ex).__name__)
            add('2.TagFamilies', fname, 'params=%d' % len(param_refs), ','.join(flags))


# ---------------------------------------------------------------- Section 3: View filters
def _walk_filter(ef, out):
    """Recursively pull FilterRule items from an ElementFilter tree."""
    if ef is None:
        return
    try:
        if isinstance(ef, ElementParameterFilter):
            for r in ef.GetRules():
                out.append(r)
        elif isinstance(ef, (LogicalAndFilter, LogicalOrFilter)):
            for sub in ef.GetFilters():
                _walk_filter(sub, out)
    except Exception:
        pass


def audit_view_filters():
    filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
    for f in filters:
        fname = f.Name
        flags = []
        if has_cyrillic(fname):
            flags.append('CYRILLIC_FILTER_NAME')
        cats = []
        try:
            for cid in f.GetCategories():
                c = Category.GetCategory(doc, cid)
                if c is not None:
                    cats.append(c.Name)
        except Exception:
            pass
        rules_repr = []
        try:
            ef = f.GetElementFilter()
            collected = []
            _walk_filter(ef, collected)
            for r in collected:
                pid = None
                val = ''
                try:
                    pid = r.GetRuleParameter()
                except Exception:
                    pass
                pname = ''
                if pid is not None:
                    if pid.IntegerValue < 0:
                        pname = 'BIP:%s' % pid.IntegerValue
                    else:
                        pe = doc.GetElement(pid)
                        if pe is not None:
                            try:
                                pname = pe.Name
                            except Exception:
                                pname = '<param>'
                if isinstance(r, FilterStringRule):
                    try:
                        val = r.RuleString
                    except Exception:
                        val = ''
                elif isinstance(r, FilterDoubleRule):
                    try:
                        val = str(r.RuleValue)
                    except Exception:
                        val = ''
                elif isinstance(r, FilterIntegerRule):
                    try:
                        val = str(r.RuleValue)
                    except Exception:
                        val = ''
                rules_repr.append('%s = "%s"' % (pname, val))
                if pname.startswith('ADSK_'):
                    flags.append('ADSK_PARAM')
                if has_cyrillic(val):
                    flags.append('CYRILLIC_VALUE')
                if has_cyrillic(pname):
                    flags.append('CYRILLIC_PARAM')
        except Exception as ex:
            flags.append('PARSE_FAIL:%s' % type(ex).__name__)
        detail = 'cats=[%s] rules=[%s]' % (', '.join(cats), ' | '.join(rules_repr))
        add('3.ViewFilters', fname, detail, ','.join(set(flags)))


# ---------------------------------------------------------------- Section 4: View templates
def audit_view_templates():
    views = FilteredElementCollector(doc).OfClass(View).ToElements()
    for v in views:
        try:
            if not v.IsTemplate:
                continue
        except Exception:
            continue
        vname = v.Name
        flags = []
        if has_cyrillic(vname):
            flags.append('CYRILLIC_NAME')
        flt_names = []
        try:
            for fid in v.GetFilters():
                fe = doc.GetElement(fid)
                if fe is not None:
                    flt_names.append(fe.Name)
        except Exception:
            pass
        add('4.ViewTemplates', vname, 'filters=[%s]' % ', '.join(flt_names), ','.join(flags))


# ---------------------------------------------------------------- Section 5: Schedules
def audit_schedules():
    schedules = FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements()
    for s in schedules:
        if s.IsTemplate:
            continue
        sname = s.Name
        flags = []
        if has_cyrillic(sname):
            flags.append('CYRILLIC_NAME')
        cat_name = ''
        try:
            cat_name = Category.GetCategory(doc, s.Definition.CategoryId).Name
        except Exception:
            pass
        field_names = []
        try:
            sd = s.Definition
            for i in range(sd.GetFieldCount()):
                fld = sd.GetField(i)
                fname = fld.GetName()
                field_names.append(fname)
                if fname and fname.startswith('ADSK_'):
                    flags.append('ADSK_FIELD')
                if has_cyrillic(fname):
                    flags.append('CYRILLIC_FIELD')
        except Exception as ex:
            flags.append('PARSE_FAIL:%s' % type(ex).__name__)
        add('5.Schedules', sname,
            'cat=%s fields=[%s]' % (cat_name, ', '.join(field_names)),
            ','.join(set(flags)))


# ---------------------------------------------------------------- Section 6: Shape families
def audit_shape_families():
    fams = FilteredElementCollector(doc).OfClass(Family).ToElements()
    for fam in fams:
        try:
            cat = fam.FamilyCategory
        except Exception:
            cat = None
        if cat is None:
            continue
        if cat.Id.IntegerValue not in (
            int(BuiltInCategory.OST_RebarShape),
            int(BuiltInCategory.OST_Rebar),
        ):
            continue
        fname = fam.Name
        flags = []
        if has_cyrillic(fname):
            flags.append('CYRILLIC_NAME')
        adsk_params = []
        try:
            fdoc = doc.EditFamily(fam)
            try:
                for p in fdoc.FamilyManager.Parameters:
                    pn = p.Definition.Name
                    if pn.startswith('ADSK_'):
                        adsk_params.append(pn)
            finally:
                fdoc.Close(False)
        except Exception as ex:
            flags.append('EDIT_FAILED:%s' % type(ex).__name__)
        if adsk_params:
            flags.append('HAS_ADSK_PARAM')
        add('6.ShapeFamilies', fname,
            'cat=%s adsk=[%s]' % (cat.Name, ', '.join(adsk_params)),
            ','.join(flags))


# ---------------------------------------------------------------- Section 7: Materials
def audit_materials():
    mats = FilteredElementCollector(doc).OfClass(Material).ToElements()
    for m in mats:
        mname = m.Name
        flags = []
        if has_cyrillic(mname):
            flags.append('CYRILLIC_NAME')
            add('7.Materials', mname, '', ','.join(flags))


# ---------------------------------------------------------------- Section 8: Subcategories of Structural Rebar
def audit_rebar_subcategories():
    cats = doc.Settings.Categories
    rebar_cat = None
    for c in cats:
        if c.Id.IntegerValue == int(BuiltInCategory.OST_Rebar):
            rebar_cat = c
            break
    if rebar_cat is None:
        return
    for sub in rebar_cat.SubCategories:
        sname = sub.Name
        flags = []
        if has_cyrillic(sname):
            flags.append('CYRILLIC_NAME')
        add('8.RebarSubcats', sname, '', ','.join(flags))


# ---------------------------------------------------------------- Run
def run():
    output.print_md('# PEER Template Audit')
    output.print_md('Document: **%s**' % doc.Title)

    steps = [
        ('Rebar types', audit_rebar_types),
        ('View filters', audit_view_filters),
        ('View templates', audit_view_templates),
        ('Schedules', audit_schedules),
        ('Materials', audit_materials),
        ('Rebar subcategories', audit_rebar_subcategories),
        ('Shape families (slow, opens each .rfa)', audit_shape_families),
        ('Tag families (slow, opens each .rfa)', audit_tag_families),
    ]
    for label, fn in steps:
        output.print_md('- running: %s' % label)
        try:
            fn()
        except Exception as ex:
            output.print_md('  - FAILED: %s' % ex)

    # Summary
    by_section = defaultdict(lambda: {'total': 0, 'flagged': 0})
    for sec, _, _, flags in rows:
        by_section[sec]['total'] += 1
        if flags:
            by_section[sec]['flagged'] += 1

    output.print_md('## Summary')
    output.print_md('| Section | Total | Flagged |')
    output.print_md('|---|---:|---:|')
    for sec in sorted(by_section):
        s = by_section[sec]
        output.print_md('| %s | %d | %d |' % (sec, s['total'], s['flagged']))

    # Flagged-only listing
    output.print_md('## Flagged items')
    last_sec = None
    for sec, name, detail, flags in rows:
        if not flags:
            continue
        if sec != last_sec:
            output.print_md('### %s' % sec)
            last_sec = sec
        output.print_md('- **%s** — %s `[%s]`' % (name, detail, flags))

    # CSV
    out_path = os.path.join(os.environ.get('TEMP', '.'), 'peer_audit_report.csv')
    try:
        with codecs.open(out_path, 'w', encoding='utf-8-sig') as fh:
            writer = csv.writer(fh)
            writer.writerow(['section', 'name', 'detail', 'flags'])
            for r in rows:
                writer.writerow([
                    (x or '').encode('utf-8') if isinstance(x, unicode) else x
                    for x in r
                ])
        output.print_md('CSV report saved: `%s`' % out_path)
    except Exception as ex:
        output.print_md('CSV save failed: %s' % ex)


run()
