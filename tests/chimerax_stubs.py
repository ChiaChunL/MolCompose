"""Reusable ChimeraX/Qt import stubs for host-light test collection."""

import sys
from types import ModuleType


def install():
    if "chimerax.core.commands" in sys.modules:
        return
    chimerax = ModuleType("chimerax")
    core = ModuleType("chimerax.core")
    toolshed = ModuleType("chimerax.core.toolshed")

    class BundleAPI:
        pass

    toolshed.BundleAPI = BundleAPI
    chimerax.core = core
    core.toolshed = toolshed

    atomic = ModuleType("chimerax.atomic")

    class Residue:
        PT_AMINO = 1

    class AtomicStructure:
        pass

    atomic.Residue = Residue
    atomic.AtomicStructure = AtomicStructure
    atomic.AtomicStructureArg = object()
    chimerax.atomic = atomic

    commands = ModuleType("chimerax.core.commands")

    class CmdDesc:
        def __init__(self, required=(), optional=(), keyword=(), synopsis=""):
            self.required = tuple(required)
            self.optional = tuple(optional)
            self.keyword = tuple(keyword)
            self.synopsis = synopsis

    class JSONResult:
        """Both forms of a return value, as ChimeraX's REST bridge expects.

        The real class lives in chimerax.core.commands.run; commands construct
        it only when a caller passes return_json=True, which in production is
        the REST bridge and in the tests is whatever is exercising that path.
        """

        def __init__(self, json_value, python_value):
            self.json_value = json_value
            self.python_value = python_value

    class StringArg:
        pass

    class FloatArg:
        pass

    class IntArg:
        pass

    class BoolArg:
        pass

    REGISTERED = {}

    def register(name, desc, function, logger=None):
        REGISTERED[name] = (desc, function)

    def run(session, text, log=True):
        return None

    commands.CmdDesc = CmdDesc
    commands.JSONResult = JSONResult
    commands.StringArg = StringArg
    commands.FloatArg = FloatArg
    commands.IntArg = IntArg
    commands.BoolArg = BoolArg
    commands.REGISTERED = REGISTERED
    commands.register = register
    commands.run = run
    core.commands = commands

    errors = ModuleType("chimerax.core.errors")

    class UserError(Exception):
        pass

    errors.UserError = UserError
    core.errors = errors

    tools = ModuleType("chimerax.core.tools")

    class ToolInstance:
        SESSION_ENDURING = False
        SESSION_SAVE = False

        def __init__(self, session, tool_name):
            self.session = session
            self.display_name = tool_name

    tools.ToolInstance = ToolInstance
    core.tools = tools

    ui = ModuleType("chimerax.ui")

    class MainToolWindow:
        def __init__(self, tool_instance, **kwargs):
            self.tool_instance = tool_instance
            self.ui_area = None

        def manage(self, placement):
            self.placement = placement

    ui.MainToolWindow = MainToolWindow
    chimerax.ui = ui

    widgets = ModuleType("chimerax.atomic.widgets")

    class AtomicStructureMenuButton:
        def __init__(self, *args, **kwargs):
            pass

    widgets.AtomicStructureMenuButton = AtomicStructureMenuButton
    atomic.widgets = widgets

    qt_pkg = ModuleType("Qt")
    qt_core = ModuleType("Qt.QtCore")

    class Qt:
        class ItemDataRole:
            UserRole = 32

        class ItemFlag:
            ItemIsEnabled = 32

        class TextInteractionFlag:
            TextSelectableByMouse = 1

        class CursorShape:
            PointingHandCursor = 13

        class MouseButton:
            LeftButton = 1

        class ScrollBarPolicy:
            ScrollBarAlwaysOff = 1

    class QProcess:
        class ProcessChannelMode:
            MergedChannels = 0

        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

    class Signal:
        """Enough of a Qt signal for a class body to define one."""

        def __init__(self, *args):
            pass

        def __get__(self, instance, owner=None):
            return self

        def connect(self, *args, **kwargs):
            return None

        def emit(self, *args, **kwargs):
            return None

    class QSize:
        """Only ever constructed and handed back to Qt, never inspected here."""

        def __init__(self, width=0, height=0):
            self._width, self._height = width, height

        def width(self):
            return self._width

        def height(self):
            return self._height

    qt_core.Qt = Qt
    qt_core.QProcess = QProcess
    qt_core.QSize = QSize
    qt_core.Signal = Signal
    qt_pkg.QtCore = qt_core

    qt_widgets = ModuleType("Qt.QtWidgets")

    class _StubWidget:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

    class _QFrame(_StubWidget):
        class Shape:
            NoFrame = 0

    qt_widgets.QFrame = _QFrame

    for widget_name in (
        "QWidget",
        "QVBoxLayout",
        "QHBoxLayout",
        "QGroupBox",
        "QLabel",
        "QLineEdit",
        "QPushButton",
        "QComboBox",
        "QListWidget",
        "QAbstractItemView",
        "QDoubleSpinBox",
        "QSpinBox",
        "QCheckBox",
        "QRadioButton",
        "QFileDialog",
        "QInputDialog",
        "QMessageBox",
        "QScrollArea",
        "QSizePolicy",
        "QListWidgetItem",
        "QTabWidget",
        "QTableWidget",
        "QTableWidgetItem",
        "QApplication",
        "QColorDialog",
        "QGridLayout",
        "QPlainTextEdit",
    ):
        setattr(qt_widgets, widget_name, type(widget_name, (_StubWidget,), {}))
    qt_gui = ModuleType("Qt.QtGui")
    for name in ("QIcon", "QPixmap", "QColor", "QFont"):
        setattr(qt_gui, name, type(name, (_StubWidget,), {}))
    qt_pkg.QtGui = qt_gui
    sys.modules["Qt.QtGui"] = qt_gui
    qt_pkg.QtWidgets = qt_widgets

    sys.modules.update(
        {
            "chimerax": chimerax,
            "chimerax.core": core,
            "chimerax.core.toolshed": toolshed,
            "chimerax.core.commands": commands,
            "chimerax.core.errors": errors,
            "chimerax.core.tools": tools,
            "chimerax.ui": ui,
            "chimerax.atomic": atomic,
            "chimerax.atomic.widgets": widgets,
            "Qt": qt_pkg,
            "Qt.QtCore": qt_core,
            "Qt.QtWidgets": qt_widgets,
        }
    )
