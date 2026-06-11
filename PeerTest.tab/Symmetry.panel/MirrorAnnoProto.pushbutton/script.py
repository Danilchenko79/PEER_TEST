# -*- coding: utf-8 -*-
__title__  = 'Mirror Anno\n(proto)'
__author__ = 'Dima'
__doc__    = '''Version = 0.1
Date      = 2026-06-10
Description:
    ПРОТОТИП ШАГ 1 (de-risking) для будущего инструмента зеркального
    оформления симметричного здания. Проверяет, можно ли аннотацию
    (один размер + один тег), привязанную к геометрии экземпляра линка A,
    пересоздать на втором экземпляре ТОГО ЖЕ линка (зеркальная копия =
    здание B) в зеркальной позиции, и резолвятся ли при этом ссылки.

    Это НЕ финальный инструмент. Суть проверки: ремаппинг ссылки на
    зеркальный экземпляр линка через хирургию stable representation
    (подмена id экземпляра линка) + перенос позиции трансформацией
    T = T_B * T_A^-1, выведенной из посадки самих линков.
How-To:
    1. Откройте план/разрез, где видны ОБА здания (или отключите подрезку).
    2. Запустите кнопку.
    3. Укажите ОДИН размер (привязанный к линку A), затем ОДИН тег.
    4. Смотрите отчёт: создались ли зеркальные размер/тег на здании B
       и какие stable-строки получились. Новые элементы выделяются —
       нажмите "Zoom to Fit Selection" (SZ), чтобы увидеть их на B.
'''

from Autodesk.Revit.DB import (
    Transaction, Reference, ReferenceArray, Line, ElementId,
    RevitLinkInstance, IndependentTag, Dimension, LeaderEndCondition,
    ElementTransformUtils, FilteredElementCollector
)
import math
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, script
from System.Collections.Generic import List

doc    = __revit__.ActiveUIDocument.Document
uidoc  = __revit__.ActiveUIDocument
output = script.get_output()


# ============================================================
# Selection filter — пускаем только нужный .NET-класс
# ============================================================
class _ClassFilter(ISelectionFilter):
    def __init__(self, cls):
        self._cls = cls

    def AllowElement(self, elem):
        return isinstance(elem, self._cls)

    def AllowReference(self, ref, pt):
        return False


# ============================================================
# Helpers
# ============================================================
def link_inst_from_ref(ref):
    """Если ссылка указывает на элемент линка — вернуть его RevitLinkInstance."""
    if ref is None or ref.LinkedElementId == ElementId.InvalidElementId:
        return None
    el = doc.GetElement(ref.ElementId)
    return el if isinstance(el, RevitLinkInstance) else None


def find_source_link(dim, tag):
    """Исходный линк A — по ссылкам размера, затем тега."""
    for r in dim.References:
        li = link_inst_from_ref(r)
        if li is not None:
            return li
    for r in tag.GetTaggedReferences():
        li = link_inst_from_ref(r)
        if li is not None:
            return li
    return None


def find_target_links(link_a):
    """Остальные экземпляры ТОГО ЖЕ типа линка — кандидаты на здание B."""
    type_id = link_a.GetTypeId()
    out = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        if li.Id != link_a.Id and li.GetTypeId() == type_id:
            out.append(li)
    return out


# ============================================================
# 0. Проверка вида
# ============================================================
view = doc.ActiveView
if view is None or view.ViewType.ToString() in ('DrawingSheet', 'Schedule', 'Legend'):
    forms.alert(u'Запустите на плане или разрезе (не на листе/спецификации/легенде).',
                title='Mirror Anno (proto)')
    script.exit()

# ============================================================
# 1. Выбор размера и тега
# ============================================================
try:
    picked_dim = uidoc.Selection.PickObject(
        ObjectType.Element, _ClassFilter(Dimension),
        u'Шаг 1/2: выберите ОДИН размер, привязанный к линку A')
    picked_tag = uidoc.Selection.PickObject(
        ObjectType.Element, _ClassFilter(IndependentTag),
        u'Шаг 2/2: выберите ОДИН тег на элементе линка A')
except OperationCanceledException:
    script.exit()

dim = doc.GetElement(picked_dim.ElementId)
tag = doc.GetElement(picked_tag.ElementId)

# ============================================================
# 2-3. Исходный линк A
# ============================================================
link_a = find_source_link(dim, tag)
if link_a is None:
    forms.alert(u'Ни размер, ни тег не привязаны к элементу линка.\n'
                u'Прототип ожидает аннотации, образмеренные ПО ЛИНКУ.',
                title='Mirror Anno (proto)')
    script.exit()

# ============================================================
# 4. Целевой линк B
# ============================================================
candidates = find_target_links(link_a)
if not candidates:
    forms.alert(u'Не найден второй экземпляр того же линка (здание B).\n'
                u'Нужно два экземпляра одного RVT в модели.',
                title='Mirror Anno (proto)')
    script.exit()
elif len(candidates) == 1:
    link_b = candidates[0]
else:
    link_b = forms.SelectFromList.show(
        candidates, name_attr='Name',
        title=u'Выберите целевой линк (здание B)',
        button_name=u'Это здание B')
    if link_b is None:
        script.exit()

# ============================================================
# 5. Трансформация A -> B (из посадки линков; зеркало учтено само)
# ============================================================
T_A = link_a.GetTotalTransform()
T_B = link_b.GetTotalTransform()
T = T_B.Multiply(T_A.Inverse)


def remap_ref(ref):
    """Пересвязать ссылку с линка A на линк B через stable representation.
    Возврат: (old_stable, new_stable, new_reference, was_linked)."""
    s = ref.ConvertToStableRepresentation(doc)
    if ref.LinkedElementId == ElementId.InvalidElementId:
        return s, s, ref, False          # не линк-ссылка — оставляем как есть
    parts = s.split(':', 1)              # parts[0] = id экземпляра линка
    new_s = str(link_b.Id.IntegerValue) + ':' + parts[1]
    new_ref = Reference.ParseFromStableRepresentation(doc, new_s)
    return s, new_s, new_ref, True


# ============================================================
# Отчёт-шапка
# ============================================================
output.print_md(u'# Mirror Anno — проверка ремаппинга ссылок')
output.print_md(u'- **Линк A (источник):** {}  `id {}`'.format(
    link_a.Name, link_a.Id.IntegerValue))
output.print_md(u'- **Линк B (цель):** {}  `id {}`'.format(
    link_b.Name, link_b.Id.IntegerValue))
output.print_md(u'- **Трансформация зеркальная (HasReflection):** {}'.format(
    T.HasReflection))

tag_log = []
dim_log = []
new_ids = List[ElementId]()
created = []   # (label, ElementId) для кликабельных ссылок

t = Transaction(doc, 'Mirror Anno proto')
t.Start()

# --- ТЕГ ---
try:
    tref = None
    for r in tag.GetTaggedReferences():
        tref = r
        break
    if tref is None:
        tag_log.append(u'У тега нет ссылок (GetTaggedReferences пуст).')
    else:
        s, ns, nref, was_linked = remap_ref(tref)
        tag_log.append(u'old: `{}`'.format(s))
        tag_log.append(u'new: `{}`'.format(ns))
        new_head = T.OfPoint(tag.TagHeadPosition)
        new_tag = IndependentTag.Create(
            doc, tag.GetTypeId(), view.Id, nref,
            tag.HasLeader, tag.TagOrientation, new_head)
        new_tag.TagHeadPosition = new_head        # фиксируем голову зеркально

        # Поворот тега (если оригинал повёрнут) — переносим через зеркало.
        # У IndependentTag нет прямого свойства угла; пробуем Location.Rotation.
        try:
            loc = tag.Location
            src_angle = getattr(loc, 'Rotation', None)
            if src_angle:
                rd = view.RightDirection
                up = view.UpDirection
                vd = view.ViewDirection
                # направление текста оригинала в плоскости вида
                d  = rd.Multiply(math.cos(src_angle)).Add(up.Multiply(math.sin(src_angle)))
                nd = T.OfVector(d).Normalize()          # зеркалим направление
                # знаковый угол от RightDirection до nd вокруг направления вида
                new_angle = math.atan2(rd.CrossProduct(nd).DotProduct(vd), rd.DotProduct(nd))
                axis = Line.CreateBound(new_head, new_head.Add(vd))
                ElementTransformUtils.RotateElement(doc, new_tag.Id, axis, new_angle)
                tag_log.append(u'  угол: оригинал {:.1f}°, применён {:.1f}°'.format(
                    math.degrees(src_angle), math.degrees(new_angle)))
            else:
                tag_log.append(u'  угол: 0 либо Location.Rotation недоступен')
        except Exception as rex:
            tag_log.append(u'  (поворот не перенесён: {})'.format(str(rex)))

        # Переносим геометрию выноски, чтобы тег сел как оригинал
        if tag.HasLeader:
            try:
                new_tag.LeaderEndCondition = tag.LeaderEndCondition
            except Exception:
                pass
            try:
                new_tag.SetLeaderElbow(nref, T.OfPoint(tag.GetLeaderElbow(tref)))
            except Exception as lex:
                tag_log.append(u'  (локоть выноски не перенесён: {})'.format(str(lex)))
            try:
                if tag.LeaderEndCondition == LeaderEndCondition.Free:
                    new_tag.SetLeaderEnd(nref, T.OfPoint(tag.GetLeaderEnd(tref)))
            except Exception as eex:
                tag_log.append(u'  (конец выноски не перенесён: {})'.format(str(eex)))

        new_ids.Add(new_tag.Id)
        created.append((u'Тег', new_tag.Id))
        tag_log.append(u'OK — создан тег `id {}`'.format(new_tag.Id.IntegerValue))
except Exception as ex:
    import traceback
    tag_log.append(u'ОШИБКА: {}'.format(str(ex)))
    tag_log.append(u'```\n{}\n```'.format(traceback.format_exc()))

# --- РАЗМЕР ---
try:
    ref_array = ReferenceArray()
    linked_cnt = 0
    for r in dim.References:
        s, ns, nref, was_linked = remap_ref(r)
        if was_linked:
            linked_cnt += 1
        dim_log.append(u'old: `{}`'.format(s))
        dim_log.append(u'new: `{}`'.format(ns))
        ref_array.Append(nref)
    crv = dim.Curve                      # у линейного размера часто НЕОГРАНИЧЕННАЯ линия
    base_pt  = crv.Origin                # точка на линии размера (есть и у unbound)
    base_dir = crv.Direction             # направление (есть и у unbound)
    new_pt   = T.OfPoint(base_pt)        # переносим точку
    new_dir  = T.OfVector(base_dir).Normalize()   # направление как вектор (зеркало учтётся)
    half = 1000.0                        # фт: заведомо длиннее пролёта — Revit подгонит размер по ссылкам
    p0 = new_pt - new_dir.Multiply(half)
    p1 = new_pt + new_dir.Multiply(half)
    new_line = Line.CreateBound(p0, p1)
    new_dim = doc.Create.NewDimension(view, new_line, ref_array)
    new_ids.Add(new_dim.Id)
    created.append((u'Размер', new_dim.Id))
    dim_log.append(u'OK — создан размер `id {}` (линк-ссылок: {})'.format(
        new_dim.Id.IntegerValue, linked_cnt))
except Exception as ex:
    import traceback
    dim_log.append(u'ОШИБКА: {}'.format(str(ex)))
    dim_log.append(u'```\n{}\n```'.format(traceback.format_exc()))

t.Commit()

# ============================================================
# Печать логов + выделение результата
# ============================================================
output.print_md(u'## Тег')
for line in tag_log:
    output.print_md(line)

output.print_md(u'## Размер')
for line in dim_log:
    output.print_md(line)

output.print_md(u'---')
if new_ids.Count > 0:
    uidoc.Selection.SetElementIds(new_ids)
    output.print_md(u'Создано элементов: **{}** — на этом же виде, но в месте '
                    u'здания B (оно смещено/зеркально от A, поэтому вне текущего '
                    u'кадра).'.format(new_ids.Count))
    for label, eid in created:
        output.print_md(u'- {}: {} — нажми на ссылку, Revit выделит и покажет элемент'.format(
            label, output.linkify(eid)))
    output.print_md(u'Либо набери в Revit **ZF** (Zoom to Fit) — кадр охватит оба здания.')
else:
    output.print_md(u'**Ничего не создано** — смотрите ошибки выше. Это тоже '
                    u'результат: значит, ссылки на линк B не резолвятся выбранным '
                    u'способом, и стратегию ремаппинга надо менять.')
