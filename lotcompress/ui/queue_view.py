"""Tableau de la file d'attente : statut et progression par fichier."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QProgressBar, QHeaderView, QAbstractItemView

from ..core.models import Task, Result, Status
from ..image.estimator import human_size

COLS = ["Fichier", "Statut", "Progression", "Avant", "Après", "Détail"]


class QueueView(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(COLS), parent)
        self.setHorizontalHeaderLabels(COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._rows: dict[int, int] = {}
        self.tasks: list[Task] = []

    def add_tasks(self, tasks: list[Task]):
        known = {t.source.resolve() for t in self.tasks}
        for t in tasks:
            if t.source.resolve() in known:
                continue
            r = self.rowCount(); self.insertRow(r)
            self._rows[t.id] = r; self.tasks.append(t)
            name = QTableWidgetItem(("🎬 " if t.kind == "video" else "") + t.source.name); name.setToolTip(str(t.source))
            self.setItem(r, 0, name)
            self.setItem(r, 1, QTableWidgetItem(Status.PENDING.value))
            bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0)
            bar.setFormat("%p %"); bar.setTextVisible(t.kind == "video")  # % affiché pour les vidéos
            self.setCellWidget(r, 2, bar)
            try:
                size = human_size(t.source.stat().st_size)
            except OSError:
                size = "?"
            for c, v in ((3, size), (4, ""), (5, "")):
                self.setItem(r, c, QTableWidgetItem(v))

    def clear_all(self):
        self.setRowCount(0); self._rows.clear(); self.tasks.clear()

    def task_at(self, row: int):
        return self.tasks[row] if 0 <= row < len(self.tasks) else None

    def pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status in (Status.PENDING, Status.CANCELLED, Status.ERROR)]

    def reset_for_run(self, tasks):
        for t in tasks:
            t.status = Status.PENDING; self.set_progress(t.id, 0)
            self.item(self._rows[t.id], 1).setText(Status.PENDING.value)

    def set_started(self, task_id: int):
        r = self._rows.get(task_id)
        if r is not None:
            self.tasks[r].status = Status.RUNNING
            self.item(r, 1).setText(Status.RUNNING.value)

    def set_progress(self, task_id: int, pct: int):
        r = self._rows.get(task_id)
        if r is not None:
            self.cellWidget(r, 2).setValue(pct)

    def set_result(self, res: Result):
        r = self._rows.get(res.task_id)
        if r is None:
            return
        self.tasks[r].status = res.status
        st = self.item(r, 1); st.setText(res.status.value)
        colors = {Status.DONE: "#10b981", Status.KEPT: "#d97706", Status.ERROR: "#ef4444",
                  Status.CANCELLED: "#6b7280"}
        if res.status in colors:
            st.setForeground(_qcolor(colors[res.status]))
        if res.status in (Status.DONE, Status.KEPT):
            self.cellWidget(r, 2).setValue(100)
            self.item(r, 4).setText(human_size(res.output_size))
        detail = res.message or (str(res.output_path) if res.output_path else "")
        if res.status == Status.DONE and res.original_size:
            detail = f"-{100 * res.saved / res.original_size:.0f} % → {res.output_path}"
        self.item(r, 5).setText(detail); self.item(r, 5).setToolTip(detail)


def _qcolor(hexstr):
    from PySide6.QtGui import QColor
    return QColor(hexstr)
