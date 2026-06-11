# -*- coding: utf-8 -*-
__title__  = 'Унификация\nАрматуры'
__author__ = 'Dima'
__doc__    = '''Version = 3.0
Date      = 2026-06-01
Description: Трёхступенчатая унификация арматуры.
   Шаг 0: выбор марки основы (хоста арматуры)
   Шаг 1: выбор формы из таблицы со сводкой
   Шаг 2: таблица параметров (A, B) + детекция перевёртышей
   Действия: Выделить в Revit, Унифицировать, Поменять A/B.
How-To:
   1. Запустите кнопку
   2. Шаг 0: выберите нужные марки основы (Ctrl/Shift)
   3. Шаг 1: выберите форму
   4. Шаг 2: выделите строки и нажмите действие
'''

# Окно немодальное (Revit остаётся доступным), поэтому движок pyRevit
# нужно держать живым после завершения скрипта.
__persistentengine__ = True

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Data')

import System
from System.Data import DataTable
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Markup import XamlReader
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, ElementId, BuiltInParameter
)
from Autodesk.Revit.DB.Structure import Rebar
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from pyrevit import forms

uiapp = __revit__
uidoc  = uiapp.ActiveUIDocument
doc    = uidoc.Document

FEET_TO_MM = 304.8
SWAP_TOL   = 30.0
NO_MARK    = u'(без марки)'


# ============================================================
# Data helpers
# ============================================================

def get_param(elem, name, ptype='string'):
    try:
        p = elem.LookupParameter(name)
        if p is None:
            return None
        if ptype == 'string':
            return p.AsString() or p.AsValueString() or ''
        elif ptype == 'double':
            return p.AsDouble()
        elif ptype == 'int':
            return p.AsInteger()
    except Exception:
        return None


def _host_mark(rb, rvt_doc):
    try:
        host = rvt_doc.GetElement(rb.GetHostId())
        if host is None:
            return NO_MARK
        p = host.LookupParameter('Mark')
        if p is None:
            p = host.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if p is not None:
            v = p.AsString() or ''
            return v if v else NO_MARK
    except Exception:
        pass
    return NO_MARK


# ============================================================
# Collection
# ============================================================

def collect_all(rvt_doc):
    """Returns (groups, swap_keys, marks_summary).

    groups   : {(shape, diam_mm, a_mm, b_mm): {count, positions, ids, mark_ids}}
               mark_ids = {mark_str: [int_ids]}
    swap_keys: set of keys that form A<->B pairs
    marks_summary: {mark_str: {count, shapes: set}}
    """
    collector = FilteredElementCollector(rvt_doc).OfClass(Rebar).ToElements()
    groups = {}
    marks_summary = {}

    for rb in collector:
        try:
            shape_num = get_param(rb, 'PR_Rebar Shape', 'int') or 0
            diam_ft   = get_param(rb, 'Bar Diameter', 'double') or 0.0
            diam_mm   = int(round(diam_ft * FEET_TO_MM))
            a_mm      = round((get_param(rb, 'PR_A', 'double') or 0.0) * FEET_TO_MM, 1)
            b_mm      = round((get_param(rb, 'PR_B', 'double') or 0.0) * FEET_TO_MM, 1)
            pos       = get_param(rb, 'PR_Position', 'string') or ''
            mark      = _host_mark(rb, rvt_doc)

            key = (shape_num, diam_mm, a_mm, b_mm)
            if key not in groups:
                groups[key] = {'count': 0, 'positions': set(),
                               'ids': [], 'mark_ids': {}}
            g = groups[key]
            g['count'] += 1
            if pos:
                g['positions'].add(pos)
            g['ids'].append(rb.Id.IntegerValue)
            g['mark_ids'].setdefault(mark, []).append(rb.Id.IntegerValue)

            if mark not in marks_summary:
                marks_summary[mark] = {'count': 0, 'shapes': set()}
            marks_summary[mark]['count'] += 1
            marks_summary[mark]['shapes'].add(shape_num)

        except Exception:
            continue

    # Swap detection
    swap_keys = set()
    klist = [k for k in groups if not (k[2] == 0 and k[3] == 0)]
    for i in range(len(klist)):
        sh1, d1, a1, b1 = klist[i]
        if a1 == 0 or b1 == 0:
            continue
        for j in range(i + 1, len(klist)):
            sh2, d2, a2, b2 = klist[j]
            if sh1 != sh2 or d1 != d2:
                continue
            if a2 == 0 or b2 == 0:
                continue
            if abs(a1 - b2) <= SWAP_TOL and abs(b1 - a2) <= SWAP_TOL:
                if abs(a1 - a2) > SWAP_TOL or abs(b1 - b2) > SWAP_TOL:
                    swap_keys.add(klist[i])
                    swap_keys.add(klist[j])

    return groups, swap_keys, marks_summary


# ============================================================
# DataTable builders
# ============================================================

def build_marks_dt(marks_summary):
    dt = DataTable()
    dt.Columns.Add('Марка', System.String)
    dt.Columns.Add('Арм.',  System.Int32)
    dt.Columns.Add('Форм',  System.Int32)
    for mark in sorted(marks_summary.keys()):
        s = marks_summary[mark]
        row = dt.NewRow()
        row['Марка'] = mark
        row['Арм.']  = s['count']
        row['Форм']  = len(s['shapes'])
        dt.Rows.Add(row)
    return dt


def build_shape_dt(groups, swap_keys, selected_marks=None):
    """Build shape summary, optionally filtered by selected_marks set."""
    shapes = {}
    for k, g in groups.items():
        sh = k[0]
        if selected_marks:
            count = sum(len(g['mark_ids'].get(m, [])) for m in selected_marks)
            if count == 0:
                continue
        else:
            count = g['count']
        if sh not in shapes:
            shapes[sh] = {'count': 0, 'variants': 0, 'swap': 0}
        shapes[sh]['count']    += count
        shapes[sh]['variants'] += 1
        if k in swap_keys:
            shapes[sh]['swap'] += 1

    dt = DataTable()
    dt.Columns.Add('Форма',     System.Int32)
    dt.Columns.Add('Элементов', System.Int32)
    dt.Columns.Add('Вариантов', System.Int32)
    dt.Columns.Add('Swap',      System.Int32)
    dt.Columns.Add('HasSwap',   System.Boolean)
    for sh in sorted(shapes.keys()):
        s = shapes[sh]
        row = dt.NewRow()
        row['Форма']     = sh
        row['Элементов'] = s['count']
        row['Вариантов'] = s['variants']
        row['Swap']      = s['swap']
        row['HasSwap']   = bool(s['swap'] > 0)
        dt.Rows.Add(row)
    return dt


def build_param_dt(groups, swap_keys, shape,
                   f_diam='Все', f_pos='', only_swap=False,
                   selected_marks=None):
    dt = DataTable()
    dt.Columns.Add('Диам',     System.Int32)
    dt.Columns.Add('A',        System.Double)
    dt.Columns.Add('B',        System.Double)
    dt.Columns.Add('Сумма',    System.Double)
    dt.Columns.Add('Кол-во',   System.Int32)
    dt.Columns.Add('Позиции',  System.String)
    dt.Columns.Add('IsUnique', System.Boolean)
    dt.Columns.Add('IsSwap',   System.Boolean)

    f_diam_str = '' if f_diam is None else str(f_diam).strip()
    f_pos_str  = '' if f_pos  is None else str(f_pos).strip()

    for key in sorted(groups.keys()):
        sh, diam, a, b = key
        if sh != shape:
            continue
        if f_diam_str and f_diam_str != 'Все':
            if str(diam) != f_diam_str:
                continue
        g = groups[key]
        if f_pos_str:
            if not any(f_pos_str in p for p in g['positions']):
                continue

        is_swap = key in swap_keys
        if only_swap and not is_swap:
            continue

        if selected_marks:
            count = sum(len(g['mark_ids'].get(m, [])) for m in selected_marks)
            if count == 0:
                continue
        else:
            count = g['count']

        pos_list = sorted(g['positions'])
        pos_str  = ', '.join(pos_list[:6])
        if len(g['positions']) > 6:
            pos_str += '...'

        row = dt.NewRow()
        row['Диам']     = diam
        row['A']        = float(a)
        row['B']        = float(b)
        row['Сумма']    = float(a + b)
        row['Кол-во']   = count
        row['Позиции']  = pos_str
        row['IsUnique'] = bool(count == 1)
        row['IsSwap']   = bool(is_swap)
        dt.Rows.Add(row)
    return dt


# ============================================================
# XAML
# ============================================================

XAML_STR = '''<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Унификация арматуры v3" Width="1020" Height="980"
    WindowStartupLocation="CenterScreen">
    <Grid Margin="10">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="160"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="160"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Унификация арматуры"
                   FontSize="16" FontWeight="Bold" Margin="0,0,0,6"/>

        <!-- STEP 0: host mark -->
        <DockPanel Grid.Row="1" Margin="0,0,0,4">
            <TextBlock Text="ШАГ 0: Марка основы" FontWeight="SemiBold"
                       Foreground="#2E7D32" VerticalAlignment="Center"/>
            <TextBlock x:Name="lblMarkHelp" Text="" Margin="14,0,0,0"
                       Foreground="#666666" FontStyle="Italic" VerticalAlignment="Center"/>
        </DockPanel>

        <DataGrid Grid.Row="2" x:Name="dgMarks"
                  AutoGenerateColumns="False"
                  SelectionMode="Extended"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  GridLinesVisibility="Horizontal"
                  HeadersVisibility="Column"
                  FontSize="13" Margin="0,0,0,8">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Марка основы" Binding="{Binding [Марка]}" Width="*"/>
                <DataGridTextColumn Header="Арматурин"    Binding="{Binding [Арм.]}"  Width="100"/>
                <DataGridTextColumn Header="Форм"         Binding="{Binding [Форм]}"  Width="70"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- STEP 1: shape -->
        <DockPanel Grid.Row="3" Margin="0,0,0,4">
            <TextBlock Text="ШАГ 1: Форма" FontWeight="SemiBold"
                       Foreground="#1565C0" VerticalAlignment="Center"/>
            <TextBlock x:Name="lblShapeHelp" Text="" Margin="14,0,0,0"
                       Foreground="#666666" FontStyle="Italic" VerticalAlignment="Center"/>
        </DockPanel>

        <DataGrid Grid.Row="4" x:Name="dgShapes"
                  AutoGenerateColumns="False"
                  SelectionMode="Single"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  GridLinesVisibility="Horizontal"
                  HeadersVisibility="Column"
                  FontSize="13" Margin="0,0,0,8">
            <DataGrid.RowStyle>
                <Style TargetType="DataGridRow">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding [HasSwap]}" Value="True">
                            <Setter Property="Background" Value="#FFE0B2"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="Форма"           Binding="{Binding [Форма]}"     Width="80"/>
                <DataGridTextColumn Header="Элементов"       Binding="{Binding [Элементов]}" Width="110"/>
                <DataGridTextColumn Header="Уник. вариантов" Binding="{Binding [Вариантов]}" Width="130"/>
                <DataGridTextColumn Header="Перевёрнутых"    Binding="{Binding [Swap]}"      Width="120"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- STEP 2: filters -->
        <Border Grid.Row="5" BorderBrush="#CCCCCC" BorderThickness="1"
                CornerRadius="3" Padding="8,6" Margin="0,0,0,4">
            <DockPanel>
                <TextBlock DockPanel.Dock="Left" Text="ШАГ 2:" FontWeight="SemiBold"
                           Foreground="#1565C0" VerticalAlignment="Center" Margin="0,0,12,0"/>
                <WrapPanel>
                    <Label Content="Диам, мм:" VerticalAlignment="Center"/>
                    <ComboBox x:Name="cbDiam" Width="70" Margin="4,0,12,0" VerticalAlignment="Center"/>
                    <Label Content="Позиция:" VerticalAlignment="Center"/>
                    <TextBox x:Name="tbPos" Width="70" Margin="4,0,12,0"
                             VerticalAlignment="Center" Height="22"/>
                    <CheckBox x:Name="cbSwapOnly" Content="Только перевёрнутые"
                              VerticalAlignment="Center" Margin="0,0,12,0"/>
                    <Button x:Name="btnFilter" Content="Применить" Padding="10,3" Margin="0,0,6,0"/>
                    <Button x:Name="btnReset"  Content="Сброс"     Padding="10,3"/>
                </WrapPanel>
            </DockPanel>
        </Border>

        <DataGrid Grid.Row="6" x:Name="dgParams"
                  AutoGenerateColumns="False"
                  SelectionMode="Extended"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  CanUserResizeColumns="True"
                  GridLinesVisibility="Horizontal"
                  HeadersVisibility="Column"
                  FontSize="13" Margin="0,0,0,6">
            <DataGrid.RowStyle>
                <Style TargetType="DataGridRow">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding [IsSwap]}" Value="True">
                            <Setter Property="Background" Value="#FFCC80"/>
                            <Setter Property="ToolTip"
                                    Value="Перевёртыш: есть пара с переставленными A и B"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding [IsUnique]}" Value="True">
                            <Setter Property="Background" Value="#FFFDE7"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="Диам, мм" Binding="{Binding [Диам]}"                    Width="80"/>
                <DataGridTextColumn Header="A, мм"    Binding="{Binding [A],     StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="B, мм"    Binding="{Binding [B],     StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="A+B, мм"  Binding="{Binding [Сумма], StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="Кол-во"   Binding="{Binding [Кол-во]}"                  Width="70"/>
                <DataGridTextColumn Header="Позиции"  Binding="{Binding [Позиции]}"                 Width="*"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- Unify controls -->
        <Border Grid.Row="7" BorderBrush="#CCCCCC" BorderThickness="1"
                CornerRadius="3" Padding="10,6" Margin="0,0,0,6">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>
                <StackPanel Grid.Row="0" Orientation="Horizontal" VerticalAlignment="Center">
                    <Label x:Name="lblSel" Content="Выбрано: 0 строк (0 элементов)"
                           FontWeight="SemiBold" Margin="0,0,16,0"/>
                    <Label Content="Параметр:" Margin="0,0,4,0"/>
                    <ComboBox x:Name="cbParam" Width="65" Margin="0,0,12,0">
                        <ComboBoxItem Content="PR_A" IsSelected="True"/>
                        <ComboBoxItem Content="PR_B"/>
                    </ComboBox>
                    <Label Content="Значение (мм):" Margin="0,0,4,0"/>
                    <TextBox x:Name="tbValue" Width="85" Height="22"/>
                </StackPanel>
                <TextBlock Grid.Row="1" x:Name="lblStatus" Text=""
                           Margin="4,4,0,0" FontStyle="Italic" Foreground="#2E7D32"/>
            </Grid>
        </Border>

        <!-- Action buttons -->
        <DockPanel Grid.Row="8">
            <Button x:Name="btnClose"  DockPanel.Dock="Right" Content="Закрыть"
                    Padding="10,5" Margin="6,0,0,0"/>
            <Button x:Name="btnUnify"  DockPanel.Dock="Right" Content="Унифицировать"
                    Padding="10,5" Margin="6,0,0,0"
                    Background="#1565C0" Foreground="White" FontWeight="Bold"/>
            <Button x:Name="btnSelect" DockPanel.Dock="Right" Content="Выделить в Revit"
                    Padding="10,5" Margin="6,0,0,0"/>
            <Button x:Name="btnSwap"   DockPanel.Dock="Right" Content="Поменять A&#8596;B"
                    Padding="10,5" Margin="6,0,0,0"
                    Background="#F57C00" Foreground="White"/>
            <Button x:Name="btnReload" DockPanel.Dock="Left"  Content="Перечитать модель"
                    Padding="10,5"/>
        </DockPanel>
    </Grid>
</Window>'''


# ============================================================
# External event handler (для немодального окна)
# ============================================================
# Любые операции с моделью (выделение, транзакции) из немодального
# окна обязаны выполняться внутри ExternalEvent.Execute — иначе Revit
# бросит "outside of API context". Обработчик просто выполняет
# отложенное действие (callable), переданное из окна.

class _RebarEventHandler(IExternalEventHandler):
    def __init__(self):
        self._action = None

    def set_action(self, fn):
        self._action = fn

    def Execute(self, uiapp):
        fn = self._action
        self._action = None
        if fn is None:
            return
        try:
            fn(uiapp)
        except Exception as ex:
            import traceback
            try:
                MessageBox.Show(
                    u'Ошибка операции:\n{}\n\n{}'.format(str(ex), traceback.format_exc()),
                    u'Ошибка', MessageBoxButton.OK)
            except Exception:
                pass

    def GetName(self):
        return 'PEER RebarUnify Handler'


# ============================================================
# Main window
# ============================================================

class RebarWindow(object):

    def __init__(self):
        self.groups, self.swap_keys, self.marks_summary = collect_all(doc)
        self.current_shape  = None
        self.selected_marks = set()   # empty = no filter (all marks)
        self._init = True             # suppress events during setup

        # ExternalEvent — мост для работы с моделью из немодального окна.
        self.handler   = _RebarEventHandler()
        self.ext_event = ExternalEvent.Create(self.handler)

        self.window = XamlReader.Parse(XAML_STR)

        self.dg_marks   = self.window.FindName('dgMarks')
        self.lbl_mark   = self.window.FindName('lblMarkHelp')
        self.dg_shapes  = self.window.FindName('dgShapes')
        self.lbl_help   = self.window.FindName('lblShapeHelp')
        self.dg_params  = self.window.FindName('dgParams')
        self.cb_diam    = self.window.FindName('cbDiam')
        self.tb_pos     = self.window.FindName('tbPos')
        self.cb_swap    = self.window.FindName('cbSwapOnly')
        self.btn_filter = self.window.FindName('btnFilter')
        self.btn_reset  = self.window.FindName('btnReset')
        self.lbl_sel    = self.window.FindName('lblSel')
        self.cb_param   = self.window.FindName('cbParam')
        self.tb_value   = self.window.FindName('tbValue')
        self.btn_swap   = self.window.FindName('btnSwap')
        self.btn_select = self.window.FindName('btnSelect')
        self.btn_unify  = self.window.FindName('btnUnify')
        self.btn_reload = self.window.FindName('btnReload')
        self.btn_close  = self.window.FindName('btnClose')
        self.lbl_status = self.window.FindName('lblStatus')

        # Populate
        self._refresh_marks()
        self._refresh_shapes()
        self._fill_diam_combo()
        self.dg_params.ItemsSource = build_param_dt(
            self.groups, self.swap_keys, -1).DefaultView

        # Wire events (after populate so _init guard works)
        self.dg_marks.SelectionChanged  += self._safe(self._on_mark_selected)
        self.dg_shapes.SelectionChanged += self._safe(self._on_shape_selected)
        self.dg_params.SelectionChanged += self._safe(self._on_params_selected)
        self.btn_filter.Click += self._safe(self._on_filter)
        self.btn_reset.Click  += self._safe(self._on_reset)
        self.btn_select.Click += self._safe(self._on_select)
        self.btn_unify.Click  += self._safe(self._on_unify)
        self.btn_swap.Click   += self._safe(self._on_swap)
        self.btn_reload.Click += self._safe(self._on_reload)
        self.btn_close.Click  += self._safe(self._on_close)

        self._init = False

        if self.dg_shapes.Items.Count > 0:
            self.dg_shapes.SelectedIndex = 0

        # Немодальный показ: Revit остаётся доступным, окно можно не закрывать.
        self.window.Show()

    # ---- defer model work to ExternalEvent ----
    def _raise(self, fn):
        """Выполнить fn(uiapp) в корректном Revit API-контексте."""
        self.handler.set_action(fn)
        self.ext_event.Raise()

    # ---- safety wrapper ----
    def _safe(self, fn):
        def wrapper(sender, args):
            if self._init:
                return
            try:
                fn(sender, args)
            except Exception as ex:
                import traceback
                try:
                    MessageBox.Show(
                        'Ошибка:\n{}\n\n{}'.format(str(ex), traceback.format_exc()),
                        'Ошибка', MessageBoxButton.OK)
                except Exception:
                    pass
        return wrapper

    # ---- row value helper ----
    def _row_get(self, row, col_name, col_index):
        for fn in (lambda: row[col_name],
                   lambda: row.Row[col_name],
                   lambda: row[col_index]):
            try:
                v = fn()
                if v is not None:
                    return v
            except Exception:
                pass
        return None

    # ---- marks (Step 0) ----
    def _refresh_marks(self):
        dt = build_marks_dt(self.marks_summary)
        self.dg_marks.ItemsSource = dt.DefaultView
        total = sum(s['count'] for s in self.marks_summary.values())
        self.lbl_mark.Text = u'Всего: {} эл., {} хостов. Выберите строки для фильтрации.'.format(
            total, len(self.marks_summary))

    def _on_mark_selected(self, sender, args):
        selected = set()
        for row in self.dg_marks.SelectedItems:
            m = self._row_get(row, 'Марка', 0)
            if m is not None:
                selected.add(str(m))
        # all or none selected => no filter
        if len(selected) == 0 or len(selected) == len(self.marks_summary):
            self.selected_marks = set()
        else:
            self.selected_marks = selected
        self.current_shape = None
        self._refresh_shapes()
        self._fill_diam_combo()
        self.dg_params.ItemsSource = build_param_dt(
            self.groups, self.swap_keys, -1).DefaultView
        self._update_sel_label()

    # ---- shapes (Step 1) ----
    def _refresh_shapes(self):
        sm = self.selected_marks if self.selected_marks else None
        dt = build_shape_dt(self.groups, self.swap_keys, sm)
        self.dg_shapes.ItemsSource = dt.DefaultView
        total_hosts = len(self.marks_summary)
        sel = len(self.selected_marks) if self.selected_marks else total_hosts
        self.lbl_help.Text = u'Фильтр: {} из {} хостов'.format(sel, total_hosts)

    def _on_shape_selected(self, sender, args):
        if self.dg_shapes.SelectedItem is None:
            return
        row = self.dg_shapes.SelectedItem
        sh = self._row_get(row, 'Форма', 0)
        if sh is None:
            return
        self.current_shape = int(sh)
        self._fill_diam_combo()
        self._refresh_params()

    # ---- diam combo ----
    def _fill_diam_combo(self):
        self.cb_diam.Items.Clear()
        self.cb_diam.Items.Add('Все')
        sm = self.selected_marks if self.selected_marks else None
        diams = set()
        for k, g in self.groups.items():
            if self.current_shape is not None and k[0] != self.current_shape:
                continue
            if sm and not any(g['mark_ids'].get(m) for m in sm):
                continue
            diams.add(k[1])
        for d in sorted(diams):
            self.cb_diam.Items.Add(str(d))
        self.cb_diam.SelectedIndex = 0

    # ---- params (Step 2) ----
    def _refresh_params(self):
        if self.current_shape is None:
            return
        f_diam    = str(self.cb_diam.SelectedItem or 'Все')
        f_pos     = self.tb_pos.Text or ''
        only_swap = bool(self.cb_swap.IsChecked)
        sm        = self.selected_marks if self.selected_marks else None
        dt = build_param_dt(self.groups, self.swap_keys,
                            self.current_shape, f_diam, f_pos, only_swap, sm)
        self.dg_params.ItemsSource = dt.DefaultView
        self._update_sel_label()

    def _on_filter(self, sender, args):
        self._refresh_params()

    def _on_reset(self, sender, args):
        self.cb_diam.SelectedIndex = 0
        self.tb_pos.Text = ''
        self.cb_swap.IsChecked = False
        self._refresh_params()

    def _on_params_selected(self, sender, args):
        self._update_sel_label()

    def _update_sel_label(self):
        rows = list(self.dg_params.SelectedItems)
        n_elems = 0
        for row in rows:
            v = self._row_get(row, 'Кол-во', 4)
            try:
                if v is not None:
                    n_elems += int(v)
            except Exception:
                pass
        self.lbl_sel.Content = u'Выбрано: {} строк ({} элементов)'.format(
            len(rows), n_elems)

    # ---- key / id helpers ----
    def _selected_keys(self):
        keys = []
        if self.current_shape is None:
            return keys
        for row in self.dg_params.SelectedItems:
            try:
                d = self._row_get(row, 'Диам', 0)
                a = self._row_get(row, 'A',    1)
                b = self._row_get(row, 'B',    2)
                if None in (d, a, b):
                    continue
                d = int(d); a = float(a); b = float(b)
                key = (self.current_shape, d, round(a, 1), round(b, 1))
                if key in self.groups:
                    keys.append(key)
                    continue
                for k in self.groups:
                    if (k[0] == self.current_shape and k[1] == d
                            and abs(k[2] - a) < 0.05
                            and abs(k[3] - b) < 0.05):
                        keys.append(k)
                        break
            except Exception:
                pass
        return keys

    def _get_filtered_ids(self, key):
        g = self.groups[key]
        if not self.selected_marks:
            return list(g['ids'])
        ids = []
        for mark in self.selected_marks:
            ids.extend(g['mark_ids'].get(mark, []))
        return ids

    def _selected_ids(self):
        ids = []
        for k in self._selected_keys():
            ids.extend(self._get_filtered_ids(k))
        return ids

    # ---- actions ----
    def _set_status(self, text, ok=True):
        try:
            self.lbl_status.Text = text
            self.lbl_status.Foreground = (
                System.Windows.Media.Brushes.Green if ok
                else System.Windows.Media.Brushes.OrangeRed)
        except Exception:
            pass

    def _on_select(self, sender, args):
        ids = self._selected_ids()
        if not ids:
            self._set_status(u'Нет выбранных строк — выделите строки в таблице.', ok=False)
            return

        def action(uiapp):
            id_list = List[ElementId]([ElementId(i) for i in ids])
            uidoc.Selection.SetElementIds(id_list)
            try:
                uidoc.ShowElements(id_list)
            except Exception:
                pass
            self._set_status(
                u'Выделено в Revit: {} элементов. Окно можно не закрывать.'.format(len(ids)))

        self._raise(action)

    def _on_unify(self, sender, args):
        ids = self._selected_ids()
        if not ids:
            MessageBox.Show(u'Выделите строки в нижней таблице.',
                            u'Унификация', MessageBoxButton.OK)
            return
        sel = self.cb_param.SelectedItem
        if sel is None:
            MessageBox.Show(u'Выберите параметр.', u'Ошибка', MessageBoxButton.OK)
            return
        try:
            pname = str(sel.Content)
        except Exception:
            pname = 'PR_A'

        raw = (self.tb_value.Text or '').strip().replace(',', '.')
        if not raw:
            MessageBox.Show(u'Введите значение в мм.', u'Ошибка', MessageBoxButton.OK)
            return
        try:
            tgt_mm = float(raw)
        except Exception:
            MessageBox.Show(u'Не разобрать число: "{}"'.format(raw),
                            u'Ошибка', MessageBoxButton.OK)
            return

        confirm = MessageBox.Show(
            u'Изменить {} = {:.1f} мм для {} элементов?'.format(pname, tgt_mm, len(ids)),
            u'Подтверждение', MessageBoxButton.OKCancel)
        if confirm != MessageBoxResult.OK:
            return

        value_ft = tgt_mm / FEET_TO_MM

        def action(uiapp):
            changed, errors = self._apply_set(ids, pname, value_ft)
            self._reload_and_refresh()
            self._set_status(u'')
            msg = u'Изменено: {} элементов'.format(changed)
            if errors:
                msg += u'\nОшибок: {}\n\n{}'.format(len(errors), '\n'.join(errors[:5]))
            MessageBox.Show(msg, u'Готово', MessageBoxButton.OK)

        self._raise(action)

    def _on_swap(self, sender, args):
        ids = self._selected_ids()
        if not ids:
            MessageBox.Show(u'Выделите строки в нижней таблице.',
                            u'A<->B', MessageBoxButton.OK)
            return
        confirm = MessageBox.Show(
            u'Поменять местами PR_A <-> PR_B для {} элементов?'.format(len(ids)),
            u'Подтверждение', MessageBoxButton.OKCancel)
        if confirm != MessageBoxResult.OK:
            return

        def action(uiapp):
            changed, errors = self._apply_swap(ids)
            self._reload_and_refresh()
            self._set_status(u'')
            msg = u'Поменяно A<->B: {} элементов'.format(changed)
            if errors:
                msg += u'\nОшибок: {}\n\n{}'.format(len(errors), '\n'.join(errors[:5]))
            MessageBox.Show(msg, u'Готово', MessageBoxButton.OK)

        self._raise(action)

    def _on_reload(self, sender, args):
        self._reload_and_refresh()

    def _on_close(self, sender, args):
        self.window.Close()

    # ---- transactions ----
    def _apply_set(self, ids, param_name, value_ft):
        changed = 0
        errors  = []
        t = Transaction(doc, u'Унификация {}'.format(param_name))
        t.Start()
        try:
            for eid in ids:
                try:
                    el = doc.GetElement(ElementId(eid))
                    if el is None:
                        continue
                    p = el.LookupParameter(param_name)
                    if p is not None and not p.IsReadOnly:
                        p.Set(value_ft)
                        changed += 1
                    else:
                        errors.append('ID {}: {} недоступен'.format(eid, param_name))
                except Exception as ex:
                    errors.append('ID {}: {}'.format(eid, str(ex)))
            t.Commit()
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            errors.append('Transaction: {}'.format(str(ex)))
        return changed, errors

    def _apply_swap(self, ids):
        changed = 0
        errors  = []
        t = Transaction(doc, 'Swap PR_A <-> PR_B')
        t.Start()
        try:
            for eid in ids:
                try:
                    el = doc.GetElement(ElementId(eid))
                    if el is None:
                        continue
                    pA = el.LookupParameter('PR_A')
                    pB = el.LookupParameter('PR_B')
                    if pA is None or pB is None or pA.IsReadOnly or pB.IsReadOnly:
                        errors.append('ID {}: PR_A или PR_B недоступен'.format(eid))
                        continue
                    a = pA.AsDouble()
                    b = pB.AsDouble()
                    pA.Set(b)
                    pB.Set(a)
                    changed += 1
                except Exception as ex:
                    errors.append('ID {}: {}'.format(eid, str(ex)))
            t.Commit()
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            errors.append('Transaction: {}'.format(str(ex)))
        return changed, errors

    # ---- reload after edit ----
    def _reload_and_refresh(self):
        prev_shape = self.current_shape
        prev_marks = set(self.selected_marks)
        self._init = True
        self.groups, self.swap_keys, self.marks_summary = collect_all(doc)
        self.selected_marks = prev_marks
        self._refresh_marks()
        self._refresh_shapes()
        self._fill_diam_combo()
        # Restore shape selection
        if prev_shape is not None:
            for i in range(self.dg_shapes.Items.Count):
                row = self.dg_shapes.Items[i]
                sh = self._row_get(row, 'Форма', 0)
                if sh is not None and int(sh) == prev_shape:
                    self._init = False
                    self.dg_shapes.SelectedIndex = i
                    return
        self._init = False
        self._refresh_params()


# ============================================================
# Entry point
# ============================================================
try:
    # Глобальная ссылка нужна, чтобы немодальное окно и его ExternalEvent
    # не были собраны GC после завершения скрипта.
    __rebar_unify_window__ = RebarWindow()
except Exception as ex:
    import traceback
    try:
        forms.alert(
            u'Ошибка запуска:\n{}\n\n{}'.format(str(ex), traceback.format_exc()),
            title='RebarUnify')
    except Exception:
        pass
