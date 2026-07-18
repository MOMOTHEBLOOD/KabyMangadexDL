import os
import threading
import queue
import time
from urllib.parse import urlparse

from mangadex_api import (
    get_chapter_images,
    download_image,
    chapter_label,
    sanitize,
)


class DownloadTask:
    """一个下载任务：一部漫画 + 选中的章节 + 输出设置"""

    STATUS_PENDING = "等待中"
    STATUS_RUNNING = "下载中"
    STATUS_DONE = "已完成"
    STATUS_ERROR = "出错"
    STATUS_CANCELLED = "已取消"

    _next_id = 1

    def __init__(self, manga_id, manga_title, chapters, out_dir, as_cbz, data_saver):
        self.task_id = DownloadTask._next_id
        DownloadTask._next_id += 1

        self.manga_id = manga_id
        self.manga_title = manga_title
        self.chapters = chapters  # list of chapter dict (api格式)
        self.out_dir = out_dir
        self.as_cbz = as_cbz
        self.data_saver = data_saver

        self.status = self.STATUS_PENDING
        self.progress = 0          # 0~100
        self.current_label = ""
        self.cancelled = False
        self.error_msg = ""


class DownloadQueueManager:
    """
    管理多个 DownloadTask 的并发下载。
    max_concurrent 控制同时跑几个任务，避免同时对API发太多请求。
    """

    def __init__(self, max_concurrent=2, log_func=print, on_update=None):
        self.max_concurrent = max_concurrent
        self.log_func = log_func
        self.on_update = on_update or (lambda task: None)
        self.tasks = []
        self._task_queue = queue.Queue()
        self._workers = []
        self._lock = threading.Lock()
        self._running = False

    def add_task(self, task: DownloadTask):
        self.tasks.append(task)
        self._task_queue.put(task)
        self.on_update(task)

    def start(self):
        if self._running:
            return
        self._running = True
        for _ in range(self.max_concurrent):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def cancel_task(self, task: DownloadTask):
        task.cancelled = True

    def _worker_loop(self):
        while True:
            try:
                task = self._task_queue.get(timeout=1)
            except queue.Empty:
                if not self._running:
                    return
                continue
            if task.cancelled:
                task.status = DownloadTask.STATUS_CANCELLED
                self.on_update(task)
                continue
            self._run_task(task)

    def _run_task(self, task: DownloadTask):
        task.status = DownloadTask.STATUS_RUNNING
        self.on_update(task)

        manga_dir = os.path.join(task.out_dir, sanitize(task.manga_title))
        os.makedirs(manga_dir, exist_ok=True)

        total = len(task.chapters)
        try:
            for i, ch in enumerate(task.chapters, start=1):
                if task.cancelled:
                    task.status = DownloadTask.STATUS_CANCELLED
                    self.on_update(task)
                    return

                label = chapter_label(ch)
                task.current_label = label
                self.log_func(f"[{task.manga_title}] 下载 {label} ({i}/{total})")

                chapter_dir = os.path.join(manga_dir, label)
                os.makedirs(chapter_dir, exist_ok=True)

                urls = get_chapter_images(ch["id"], data_saver=task.data_saver)
                for j, url in enumerate(urls, start=1):
                    if task.cancelled:
                        break
                    ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
                    dest = os.path.join(chapter_dir, f"{j:03d}{ext}")
                    if not os.path.exists(dest):
                        download_image(url, dest)

                if task.as_cbz:
                    self._pack_cbz(chapter_dir, manga_dir, label)

                task.progress = int(i / total * 100)
                self.on_update(task)

            task.status = DownloadTask.STATUS_DONE
            task.progress = 100
            self.log_func(f"[{task.manga_title}] 全部完成")
        except Exception as e:
            task.status = DownloadTask.STATUS_ERROR
            task.error_msg = str(e)
            self.log_func(f"[{task.manga_title}] 出错: {e}")
        self.on_update(task)

    @staticmethod
    def _pack_cbz(chapter_dir, manga_dir, label):
        import zipfile
        import shutil

        cbz_path = os.path.join(manga_dir, f"{label}.cbz")
        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(chapter_dir)):
                zf.write(os.path.join(chapter_dir, fname), fname)
        shutil.rmtree(chapter_dir)
