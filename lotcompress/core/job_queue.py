"""File d'attente multithread (QThreadPool) avec annulation coopérative.

Les images utilisent un pool de threads ; les vidéos un pool séparé limité
(1 encodage à la fois sur GPU, 2 sur processeur) pour ne pas saturer la machine.
"""
import threading
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .. import config
from ..presets import ImageSettings, VideoSettings
from ..image.compressor import process_task
from .models import Task, Result, Status


class QueueSignals(QObject):
    progress = Signal(int, int)          # task_id, pourcentage
    started = Signal(int)                # task_id
    finished = Signal(object)            # Result
    all_done = Signal()


class _Job(QRunnable):
    def __init__(self, task: Task, settings, cancel: threading.Event, owner: "JobQueue"):
        super().__init__()
        self.task, self.settings, self.cancel, self.owner = task, settings, cancel, owner

    def run(self):
        s = self.owner.signals
        try:
            if self.cancel.is_set():
                res = Result(self.task.id, Status.CANCELLED, message="Annulé")
            else:
                s.started.emit(self.task.id)
                report = lambda p: s.progress.emit(self.task.id, p)
                if getattr(self.settings, "_is_meta", False):
                    from ..metadata.operations import process_metadata_task
                    res = process_metadata_task(self.task, self.settings, self.cancel, report)
                elif self.task.kind == "video":
                    from ..video.compressor import process_video_task  # import paresseux
                    res = process_video_task(self.task, self.settings, self.cancel, report)
                else:
                    res = process_task(self.task, self.settings, self.cancel, report)
        except Exception as e:  # Filet de sécurité : jamais de plantage du pool
            res = Result(self.task.id, Status.ERROR, message=f"Erreur inattendue : {e}")
        s.finished.emit(res)
        self.owner._job_done()


class JobQueue(QObject):
    """Lance les tâches en arrière-plan ; l'interface ne bloque jamais.

    L'annulation positionne un Event partagé : chaque tâche s'arrête proprement,
    et les processus FFmpeg en cours reçoivent « q » puis sont terminés.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = QueueSignals()
        self.pool = QThreadPool()
        self.video_pool = QThreadPool()
        self.video_pool.setMaxThreadCount(config.VIDEO_WORKERS_CPU)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._remaining = 0

    @property
    def running(self) -> bool:
        return self._remaining > 0

    def start(self, tasks: list[Task], settings: ImageSettings,
              video_settings: Optional[VideoSettings] = None) -> None:
        self._cancel = threading.Event()
        video_settings = video_settings or VideoSettings()
        self._remaining = len(tasks)
        if not tasks:
            self.signals.all_done.emit()
            return
        if any(t.kind == "video" for t in tasks):
            workers = config.VIDEO_WORKERS_CPU
            if video_settings.use_gpu:
                from ..video.gpu import choose_encoder
                if choose_encoder(video_settings.codec, True).family != "cpu":
                    workers = config.VIDEO_WORKERS_GPU
            self.video_pool.setMaxThreadCount(workers)
        for t in tasks:
            if t.kind == "video":
                vs = video_settings.with_(overwrite=settings.overwrite, output_dir=settings.output_dir)
                self.video_pool.start(_Job(t, vs, self._cancel, self))
            else:
                self.pool.start(_Job(t, settings, self._cancel, self))

    def start_metadata(self, tasks: list[Task], ops) -> None:
        """Applique des opérations de métadonnées (MetaOps) à un lot, dans le pool d'images."""
        self._cancel = threading.Event()
        self._remaining = len(tasks)
        if not tasks:
            self.signals.all_done.emit()
            return
        for t in tasks:
            self.pool.start(_Job(t, ops, self._cancel, self))

    def cancel(self) -> None:
        self._cancel.set()

    def _job_done(self):
        with self._lock:
            self._remaining -= 1
            done = self._remaining == 0
        if done:
            self.signals.all_done.emit()

    def wait(self, ms: int = -1) -> bool:
        a = self.pool.waitForDone(ms)
        return self.video_pool.waitForDone(ms) and a
