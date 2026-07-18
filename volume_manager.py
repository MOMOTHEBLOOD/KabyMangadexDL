import json
from pathlib import Path

class Volume:
    def __init__(self, name, chapters=None):
        self.name = name
        self.chapters = chapters if chapters else []   # 存放 Chapter 对象

    def add_chapter(self, chapter):
        if chapter not in self.chapters:
            self.chapters.append(chapter)
            chapter.volume = self

    def remove_chapter(self, chapter):
        if chapter in self.chapters:
            self.chapters.remove(chapter)
            chapter.volume = None

    def to_dict(self):
        return {
            "name": self.name,
            "chapters": [ch.id for ch in self.chapters]
        }

    @classmethod
    def from_dict(cls, data, chapter_map):
        vol = cls(data["name"])
        for ch_id in data.get("chapters", []):
            if ch_id in chapter_map:
                vol.add_chapter(chapter_map[ch_id])
        return vol


class Project:
    def __init__(self, title="", author="", language="zh"):
        self.title = title
        self.author = author
        self.language = language
        self.volumes = []
        self.chapters = []        # 所有扫描到的 Chapter 对象
        self.unassigned = []      # 未分配卷的章节（引用）

    def add_volume(self, vol):
        self.volumes.append(vol)

    def remove_volume(self, vol):
        # 移除前将章节设为未分配
        for ch in vol.chapters:
            ch.volume = None
            self.unassigned.append(ch)
        self.volumes.remove(vol)

    def assign_chapter_to_volume(self, chapter, volume):
        if chapter in self.unassigned:
            self.unassigned.remove(chapter)
        # 如果原属于其他卷，先移除
        if chapter.volume:
            chapter.volume.remove_chapter(chapter)
        volume.add_chapter(chapter)

    def unassign_chapter(self, chapter):
        if chapter.volume:
            chapter.volume.remove_chapter(chapter)
        if chapter not in self.unassigned:
            self.unassigned.append(chapter)

    def to_dict(self):
        return {
            "title": self.title,
            "author": self.author,
            "language": self.language,
            "volumes": [v.to_dict() for v in self.volumes]
        }

    def save(self, file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, file_path, chapter_map):
        """从 JSON 恢复 Project，需要 chapter_map (id->Chapter)"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        proj = cls(data.get("title", ""), data.get("author", ""), data.get("language", "zh"))
        for vdata in data.get("volumes", []):
            vol = Volume.from_dict(vdata, chapter_map)
            proj.add_volume(vol)
        # 未分配章节：所有章节中未在任何卷中的
        assigned_ids = set()
        for vol in proj.volumes:
            for ch in vol.chapters:
                assigned_ids.add(ch.id)
        proj.unassigned = [ch for ch in chapter_map.values() if ch.id not in assigned_ids]
        return proj