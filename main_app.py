#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manga Suite - 主程序
------------------------------------
三个标签页：
  1. 下载队列：点"+"新建下载任务，可同时跑多部漫画（并发数在设置里调）
  2. 卷本构建：扫描已下载的章节文件夹，手动拖拽式分卷 或 自动每N话一卷，导出 cbz/epub/pdf
  3. 设置：默认输出目录、并发数、分卷章数、导出格式等

依赖：
  pip install requests pillow ebooklib
"""

import os
import re
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import settings as settings_mod
from mangadex_api import search_manga, get_manga_title, extract_manga_id, get_chapter_feed
from download_manager import DownloadTask, DownloadQueueManager
from builder import scan_chapters, auto_group_chapters
from volume_manager import Project, Volume
from exporter import export_volume

CHECK_ON = "☑"
CHECK_OFF = "☐"
COMMON_LANGS = ["en", "zh", "zh-hk", "ja", "ko", "vi", "id", "th", "fr", "es-la", "pt-br", "ru", "de"]


# ============================================================
# 新建下载任务 弹窗
# ============================================================
class AddTaskDialog(tk.Toplevel):
    def __init__(self, parent, default_settings, on_confirm):
        super().__init__(parent)
        self.title("新建下载任务")
        self.geometry("760x560")
        self.on_confirm = on_confirm
        self.default_settings = default_settings

        self.manga_id = None
        self.manga_title = ""
        self.chapters = []
        self.chapter_selected = {}

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="漫画网址 或 标题：").pack(side="left")
        self.url_entry = ttk.Entry(top, width=45)
        self.url_entry.pack(side="left", padx=4)
        self.url_entry.bind("<Return>", lambda e: self.on_load())
        ttk.Button(top, text="搜索/载入", command=self.on_load).pack(side="left", padx=4)

        ttk.Label(top, text=" 语言：").pack(side="left")
        self.lang_var = tk.StringVar(value=self.default_settings.get("default_lang", "en"))
        ttk.Combobox(top, textvariable=self.lang_var, values=COMMON_LANGS, width=8).pack(side="left")

        self.title_label = ttk.Label(self, text="", foreground="#1a73e8")
        self.title_label.pack(anchor="w", padx=8)

        # 章节列表
        tree_frm = ttk.Frame(self, padding=(8, 4))
        tree_frm.pack(fill="both", expand=True)
        cols = ("sel", "vol", "chapter", "title")
        self.tree = ttk.Treeview(tree_frm, columns=cols, show="headings", selectmode="none", height=14)
        for c, w, t in [("sel", 40, "选"), ("vol", 50, "卷"), ("chapter", 60, "话"), ("title", 420, "章节标题")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c != "title" else "w")
        vsb = ttk.Scrollbar(tree_frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self.on_tree_click)

        btn_frm = ttk.Frame(self, padding=(8, 0))
        btn_frm.pack(fill="x")
        ttk.Button(btn_frm, text="全选", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(btn_frm, text="全不选", command=lambda: self.set_all(False)).pack(side="left", padx=4)

        # 输出选项
        opt_frm = ttk.Frame(self, padding=8)
        opt_frm.pack(fill="x")
        ttk.Label(opt_frm, text="输出目录：").pack(side="left")
        self.out_var = tk.StringVar(value=self.default_settings.get("output_dir", "./downloads"))
        ttk.Entry(opt_frm, textvariable=self.out_var, width=35).pack(side="left", padx=4)
        ttk.Button(opt_frm, text="浏览...", command=self.choose_dir).pack(side="left")

        self.cbz_var = tk.BooleanVar(value=self.default_settings.get("default_cbz", True))
        ttk.Checkbutton(opt_frm, text="下载完打包cbz", variable=self.cbz_var).pack(side="left", padx=10)
        self.datasaver_var = tk.BooleanVar(value=self.default_settings.get("default_data_saver", False))
        ttk.Checkbutton(opt_frm, text="省流画质", variable=self.datasaver_var).pack(side="left")

        ttk.Button(self, text="添加到队列", command=self.confirm).pack(pady=8)

    def choose_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def on_load(self):
        text = self.url_entry.get().strip()
        if not text:
            return
        threading.Thread(target=self._load_worker, args=(text,), daemon=True).start()

    def _load_worker(self, text):
        try:
            if re.search(r"/title/[0-9a-fA-F-]{36}", text):
                manga_id = extract_manga_id(text)
            elif re.fullmatch(r"[0-9a-fA-F-]{36}", text):
                manga_id = text
            else:
                results = search_manga(text, limit=8)
                if not results:
                    return
                self.after(0, lambda: self._show_search_results(results))
                return
            self._load_by_id(manga_id)
        except Exception as e:
            messagebox.showerror("载入失败", str(e))

    def _show_search_results(self, results):
        win = tk.Toplevel(self)
        win.title("选择漫画")
        win.geometry("400x280")
        lb = tk.Listbox(win, font=("Consolas", 10))
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for r in results:
            lb.insert("end", r["title"])

        def on_pick(event=None):
            sel = lb.curselection()
            if not sel:
                return
            manga_id = results[sel[0]]["id"]
            win.destroy()
            threading.Thread(target=self._load_by_id, args=(manga_id,), daemon=True).start()

        lb.bind("<Double-Button-1>", on_pick)
        ttk.Button(win, text="选择", command=on_pick).pack(pady=4)

    def _load_by_id(self, manga_id):
        self.manga_id = manga_id
        self.manga_title = get_manga_title(manga_id)
        lang = self.lang_var.get().strip() or "en"
        chapters = get_chapter_feed(manga_id, lang)

        def chapter_num(ch):
            try:
                return float(ch["attributes"]["chapter"])
            except (TypeError, ValueError):
                return -1

        chapters.sort(key=chapter_num)
        self.chapters = chapters
        self.chapter_selected = {c["id"]: True for c in chapters}
        self.after(0, self._populate_tree)
        self.after(0, lambda: self.title_label.configure(text=f"{self.manga_title} （共{len(chapters)}话）"))

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for ch in self.chapters:
            attr = ch["attributes"]
            self.tree.insert(
                "", "end", iid=ch["id"],
                values=(CHECK_ON, attr.get("volume") or "", attr.get("chapter") or "", attr.get("title") or ""),
            )

    def on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or col != "#1":
            return
        self.chapter_selected[row] = not self.chapter_selected.get(row, True)
        vals = list(self.tree.item(row, "values"))
        vals[0] = CHECK_ON if self.chapter_selected[row] else CHECK_OFF
        self.tree.item(row, values=vals)

    def set_all(self, value):
        for ch in self.chapters:
            self.chapter_selected[ch["id"]] = value
        self._populate_tree()

    def confirm(self):
        if not self.manga_id:
            messagebox.showwarning("提示", "先载入一部漫画")
            return
        selected = [c for c in self.chapters if self.chapter_selected.get(c["id"], False)]
        if not selected:
            messagebox.showwarning("提示", "没有选中任何章节")
            return
        task = DownloadTask(
            manga_id=self.manga_id,
            manga_title=self.manga_title,
            chapters=selected,
            out_dir=self.out_var.get().strip() or "./downloads",
            as_cbz=self.cbz_var.get(),
            data_saver=self.datasaver_var.get(),
        )
        self.on_confirm(task)
        self.destroy()


# ============================================================
# 下载队列 标签页
# ============================================================
class DownloadTab(ttk.Frame):
    def __init__(self, parent, app_settings, log_func):
        super().__init__(parent)
        self.app_settings = app_settings
        self.log_func = log_func
        self.manager = DownloadQueueManager(
            max_concurrent=app_settings.get("max_concurrent_downloads", 2),
            log_func=log_func,
            on_update=self._on_task_update,
        )
        self._build_ui()

    def _build_ui(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="＋ 新建下载任务", command=self.open_add_dialog).pack(side="left")
        ttk.Button(bar, text="开始下载队列", command=self.start_queue).pack(side="left", padx=6)
        ttk.Button(bar, text="取消选中任务", command=self.cancel_selected).pack(side="left")

        cols = ("title", "status", "progress", "current")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        for c, w, t in [("title", 260, "漫画标题"), ("status", 90, "状态"), ("progress", 80, "进度"), ("current", 260, "当前章节")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        self._task_row = {}

    def open_add_dialog(self):
        AddTaskDialog(self, self.app_settings, self.add_task)

    def add_task(self, task: DownloadTask):
        self.manager.add_task(task)
        iid = f"task_{task.task_id}"
        self._task_row[task.task_id] = iid
        self.tree.insert("", "end", iid=iid, values=(task.manga_title, task.status, "0%", ""))

    def start_queue(self):
        self.manager.start()
        self.log_func("下载队列已启动")

    def cancel_selected(self):
        sel = self.tree.selection()
        for iid in sel:
            task_id = int(iid.replace("task_", ""))
            for t in self.manager.tasks:
                if t.task_id == task_id:
                    self.manager.cancel_task(t)

    def _on_task_update(self, task: DownloadTask):
        iid = self._task_row.get(task.task_id)
        if not iid:
            return
        # tkinter 不是线程安全的，用 after 切回主线程更新
        self.after(0, lambda: self._update_row(iid, task))

    def _update_row(self, iid, task):
        try:
            self.tree.item(iid, values=(task.manga_title, task.status, f"{task.progress}%", task.current_label))
        except tk.TclError:
            pass


# ============================================================
# 卷本构建 标签页
# ============================================================
class VolumeTab(ttk.Frame):
    def __init__(self, parent, app_settings, log_func):
        super().__init__(parent)
        self.app_settings = app_settings
        self.log_func = log_func
        self.project = None
        self._build_ui()

    def _build_ui(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="扫描章节文件夹", command=self.scan_folder).pack(side="left")
        ttk.Button(bar, text="新建空卷", command=self.new_volume).pack(side="left", padx=6)
        ttk.Button(bar, text="自动分组未分配章节", command=self.auto_group_unassigned).pack(side="left")
        ttk.Button(bar, text="重命名选中卷", command=self.rename_volume).pack(side="left", padx=6)
        ttk.Button(bar, text="删除选中卷", command=self.delete_volume).pack(side="left")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(body, text="未分配章节（可多选）")
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.unassigned_list = tk.Listbox(left, selectmode="extended", font=("Consolas", 10))
        self.unassigned_list.pack(fill="both", expand=True, padx=4, pady=4)

        mid = ttk.Frame(body)
        mid.pack(side="left", fill="y", padx=4)
        ttk.Button(mid, text="加入 →\n选中卷", command=self.assign_to_volume).pack(pady=6)
        ttk.Button(mid, text="← 移出\n所选卷", command=self.unassign_from_volume).pack(pady=6)

        right = ttk.LabelFrame(body, text="卷列表（章节是子节点，可多选移出）")
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.vol_tree = ttk.Treeview(right, show="tree", selectmode="extended")
        self.vol_tree.pack(fill="both", expand=True, padx=4, pady=4)

        # 导出区
        exp_frm = ttk.Frame(self, padding=8)
        exp_frm.pack(fill="x")
        ttk.Label(exp_frm, text="导出格式：").pack(side="left")
        self.fmt_var = tk.StringVar(value=self.app_settings.get("export_format", "cbz"))
        ttk.Combobox(exp_frm, textvariable=self.fmt_var, values=["cbz", "epub", "pdf", "folder"], width=8).pack(side="left")
        ttk.Label(exp_frm, text=" 输出目录：").pack(side="left")
        self.out_var = tk.StringVar(value=os.path.join(self.app_settings.get("output_dir", "./downloads"), "volumes"))
        ttk.Entry(exp_frm, textvariable=self.out_var, width=35).pack(side="left", padx=4)
        ttk.Button(exp_frm, text="浏览...", command=self._choose_out_dir).pack(side="left")
        ttk.Button(exp_frm, text="导出选中卷", command=self.export_selected).pack(side="left", padx=10)
        ttk.Button(exp_frm, text="导出全部卷", command=self.export_all).pack(side="left")

    # ---------- 数据 ----------
    def scan_folder(self):
        d = filedialog.askdirectory(title="选择包含各章节子文件夹的目录")
        if not d:
            return
        try:
            chapters = scan_chapters(d)
        except Exception as e:
            messagebox.showerror("扫描失败", str(e))
            return
        self.project = Project(title=os.path.basename(d.rstrip("/\\")))
        self.project.chapters = chapters
        self.project.unassigned = chapters[:]
        self.log_func(f"扫描到 {len(chapters)} 个章节")
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_unassigned()
        self._refresh_volumes()

    def _refresh_unassigned(self):
        self.unassigned_list.delete(0, "end")
        if not self.project:
            return
        for ch in self.project.unassigned:
            self.unassigned_list.insert("end", f"{ch}")

    def _refresh_volumes(self):
        # 记住当前每个卷的展开/折叠状态（按卷对象身份记，不按index，避免删卷后错位）
        prev_open_state = {}
        for iid in self.vol_tree.get_children(""):
            if iid.startswith("vol_"):
                try:
                    vi = int(iid.split("_")[1])
                    vol = self.project.volumes[vi]
                    prev_open_state[id(vol)] = self.vol_tree.item(iid, "open")
                except (IndexError, ValueError):
                    pass

        self.vol_tree.delete(*self.vol_tree.get_children())
        if not self.project:
            return
        for vi, vol in enumerate(self.project.volumes):
            vol_iid = f"vol_{vi}"
            is_open = prev_open_state.get(id(vol), True)  # 新卷默认展开，见过的卷保持原状态
            self.vol_tree.insert(
                "", "end", iid=vol_iid, text=f"📘 {vol.name} ({len(vol.chapters)}话)", open=is_open
            )
            for ci, ch in enumerate(vol.chapters):
                self.vol_tree.insert(vol_iid, "end", iid=f"vol_{vi}_ch_{ci}", text=str(ch))

    def new_volume(self):
        if not self.project:
            messagebox.showwarning("提示", "先扫描一个章节文件夹")
            return
        name = simpledialog.askstring("新建卷", "卷名称：", initialvalue=f"Vol.{len(self.project.volumes)+1:02d}")
        if not name:
            return
        self.project.add_volume(Volume(name))
        self._refresh_volumes()

    def auto_group_unassigned(self):
        if not self.project or not self.project.unassigned:
            messagebox.showwarning("提示", "没有未分配的章节")
            return
        n = simpledialog.askinteger(
            "自动分组", "每多少话为一卷？", initialvalue=self.app_settings.get("volume_group_size", 10), minvalue=1
        )
        if not n:
            return
        vols = auto_group_chapters(self.project.unassigned, n)
        start_index = len(self.project.volumes)
        for i, vol in enumerate(vols):
            vol.name = f"Vol.{start_index + i + 1:02d}"
            self.project.add_volume(vol)
            for ch in vol.chapters:
                if ch in self.project.unassigned:
                    self.project.unassigned.remove(ch)
        self.log_func(f"自动分组完成：新增 {len(vols)} 卷")
        self._refresh_all()

    def _selected_unassigned_chapters(self):
        idxs = self.unassigned_list.curselection()
        return [self.project.unassigned[i] for i in idxs]

    def _selected_volume_index(self):
        sel = self.vol_tree.selection()
        for iid in sel:
            if iid.startswith("vol_") and "_ch_" not in iid:
                return int(iid.split("_")[1])
        # 如果选的是某卷下的章节，也定位到它所属的卷
        for iid in sel:
            if "_ch_" in iid:
                return int(iid.split("_")[1])
        return None

    def assign_to_volume(self):
        if not self.project:
            return
        vi = self._selected_volume_index()
        if vi is None:
            messagebox.showwarning("提示", "先在右边选中一个目标卷")
            return
        chapters = self._selected_unassigned_chapters()
        if not chapters:
            messagebox.showwarning("提示", "先在左边选中要加入的章节")
            return
        vol = self.project.volumes[vi]
        for ch in chapters:
            self.project.assign_chapter_to_volume(ch, vol)
        self._refresh_all()

    def unassign_from_volume(self):
        if not self.project:
            return
        sel = self.vol_tree.selection()
        chapters_to_remove = []
        for iid in sel:
            if "_ch_" in iid:
                parts = iid.split("_")
                vi, ci = int(parts[1]), int(parts[3])
                if vi < len(self.project.volumes) and ci < len(self.project.volumes[vi].chapters):
                    chapters_to_remove.append(self.project.volumes[vi].chapters[ci])
        for ch in chapters_to_remove:
            self.project.unassign_chapter(ch)
        self._refresh_all()

    def rename_volume(self):
        vi = self._selected_volume_index()
        if vi is None or not self.project:
            messagebox.showwarning("提示", "先选中一个卷")
            return
        vol = self.project.volumes[vi]
        name = simpledialog.askstring("重命名卷", "新名称：", initialvalue=vol.name)
        if name:
            vol.name = name
            self._refresh_volumes()

    def delete_volume(self):
        vi = self._selected_volume_index()
        if vi is None or not self.project:
            messagebox.showwarning("提示", "先选中一个卷")
            return
        vol = self.project.volumes[vi]
        if messagebox.askyesno("确认", f"删除卷 {vol.name}？里面的章节会变回未分配。"):
            self.project.remove_volume(vol)
            self._refresh_all()

    def _choose_out_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def export_selected(self):
        vi = self._selected_volume_index()
        if vi is None or not self.project:
            messagebox.showwarning("提示", "先选中一个卷")
            return
        self._export_volumes([self.project.volumes[vi]])

    def export_all(self):
        if not self.project or not self.project.volumes:
            messagebox.showwarning("提示", "还没有任何卷")
            return
        self._export_volumes(self.project.volumes)

    def _export_volumes(self, volumes):
        out_dir = self.out_var.get().strip()
        fmt = self.fmt_var.get()
        os.makedirs(out_dir, exist_ok=True)

        def worker():
            for vol in volumes:
                for ch in vol.chapters:
                    if not ch.pages:
                        ch.scan_pages()
                export_volume(vol, out_dir, fmt, title=vol.name, log_func=self.log_func)
            self.log_func("导出完成 ✅")

        threading.Thread(target=worker, daemon=True).start()


# ============================================================
# 设置 标签页
# ============================================================
class SettingsTab(ttk.Frame):
    def __init__(self, parent, app_settings, on_save):
        super().__init__(parent)
        self.app_settings = app_settings
        self.on_save = on_save
        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)

        row = 0
        ttk.Label(frm, text="默认输出目录：").grid(row=row, column=0, sticky="w", pady=6)
        self.out_var = tk.StringVar(value=self.app_settings.get("output_dir"))
        ttk.Entry(frm, textvariable=self.out_var, width=40).grid(row=row, column=1, sticky="w")
        ttk.Button(frm, text="浏览...", command=self._choose_dir).grid(row=row, column=2, padx=4)

        row += 1
        ttk.Label(frm, text="同时下载几部漫画（并发数）：").grid(row=row, column=0, sticky="w", pady=6)
        self.concurrent_var = tk.IntVar(value=self.app_settings.get("max_concurrent_downloads", 2))
        ttk.Spinbox(frm, from_=1, to=8, textvariable=self.concurrent_var, width=6).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frm, text="默认下载语言：").grid(row=row, column=0, sticky="w", pady=6)
        self.lang_var = tk.StringVar(value=self.app_settings.get("default_lang", "en"))
        ttk.Combobox(frm, textvariable=self.lang_var, values=COMMON_LANGS, width=10).grid(row=row, column=1, sticky="w")

        row += 1
        self.cbz_var = tk.BooleanVar(value=self.app_settings.get("default_cbz", True))
        ttk.Checkbutton(frm, text="下载完默认打包cbz", variable=self.cbz_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)

        row += 1
        self.datasaver_var = tk.BooleanVar(value=self.app_settings.get("default_data_saver", False))
        ttk.Checkbutton(frm, text="默认使用省流画质", variable=self.datasaver_var).grid(row=row, column=0, columnspan=2, sticky="w")

        row += 1
        ttk.Label(frm, text="自动分卷对话框的默认每卷话数：").grid(row=row, column=0, sticky="w", pady=6)
        self.group_var = tk.IntVar(value=self.app_settings.get("volume_group_size", 10))
        ttk.Spinbox(frm, from_=1, to=200, textvariable=self.group_var, width=6).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(
            frm,
            text="（这个值只会预填到「卷本构建」里点\"自动分组未分配章节\"弹出的输入框里，\n"
                 "本身不会自动执行分卷——不点那个按钮，章节永远不会被自动分组）",
            foreground="#888",
        ).grid(row=row, column=0, columnspan=3, sticky="w")

        row += 1
        ttk.Label(frm, text="默认导出格式：").grid(row=row, column=0, sticky="w", pady=6)
        self.fmt_var = tk.StringVar(value=self.app_settings.get("export_format", "cbz"))
        ttk.Combobox(frm, textvariable=self.fmt_var, values=["cbz", "epub", "pdf", "folder"], width=10).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Button(frm, text="保存设置", command=self.save).grid(row=row, column=0, pady=16, sticky="w")
        self.status_label = ttk.Label(frm, text="", foreground="#2e7d32")
        self.status_label.grid(row=row, column=1)

        note = ttk.Label(
            frm,
            text="提示：并发数别设太高，MangaDex 对请求频率有限制，2~3 比较稳。\n"
                 "重启程序后，新建的下载任务/卷本构建会用这里的默认值，但已存在的任务不受影响。",
            foreground="#666",
        )
        row += 1
        note.grid(row=row, column=0, columnspan=3, sticky="w", pady=10)

    def _choose_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def save(self):
        new_settings = {
            "output_dir": self.out_var.get().strip() or "./downloads",
            "max_concurrent_downloads": self.concurrent_var.get(),
            "default_lang": self.lang_var.get().strip() or "en",
            "default_cbz": self.cbz_var.get(),
            "default_data_saver": self.datasaver_var.get(),
            "volume_group_size": self.group_var.get(),
            "export_format": self.fmt_var.get(),
        }
        self.app_settings.update(new_settings)
        self.on_save(self.app_settings)
        self.status_label.configure(text="已保存 ✓")
        self.after(2500, lambda: self.status_label.configure(text=""))


# ============================================================
# 主程序
# ============================================================
class MangaSuiteApp:
    def __init__(self, root):
        self.root = root
        root.title("Manga Suite - 下载 / 分卷 / 导出")
        root.geometry("980x720")

        self.app_settings = settings_mod.load_settings()
        self.log_queue = queue.Queue()

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.download_tab = DownloadTab(notebook, self.app_settings, self.log)
        self.volume_tab = VolumeTab(notebook, self.app_settings, self.log)
        self.settings_tab = SettingsTab(notebook, self.app_settings, self._on_settings_saved)

        notebook.add(self.download_tab, text="下载队列")
        notebook.add(self.volume_tab, text="卷本构建")
        notebook.add(self.settings_tab, text="设置")

        log_frm = ttk.LabelFrame(root, text="日志")
        log_frm.pack(fill="both", expand=False, padx=6, pady=4)
        self.log_text = tk.Text(log_frm, height=8, state="disabled", bg="#111", fg="#0f0", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        self.root.after(100, self._poll_log)

    def log(self, msg: str):
        self.log_queue.put(msg)

    def _poll_log(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(100, self._poll_log)

    def _on_settings_saved(self, new_settings):
        settings_mod.save_settings(new_settings)
        self.log("设置已保存")


def main():
    root = tk.Tk()
    app = MangaSuiteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
