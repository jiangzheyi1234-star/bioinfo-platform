import json
import os
import time
from typing import Dict, List, Optional

from config import get_runtime_setting


class TaskRecord:
    def __init__(
        self,
        job_id: str,
        status: str = "RUNNING",
        local_fasta: str = "",
        db_path: str = "",
        task_type: str = "",
        created_at: float = None,
        task_dir: str = "",
        local_output: str = "",
    ):
        self.job_id = job_id
        self.status = status
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task_type = task_type
        self.created_at = created_at or time.time()
        self.task_dir = task_dir
        self.local_output = local_output

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "local_fasta": self.local_fasta,
            "db_path": self.db_path,
            "task_type": self.task_type,
            "created_at": self.created_at,
            "task_dir": self.task_dir,
            "local_output": self.local_output,
        }

    @staticmethod
    def from_dict(data: dict) -> "TaskRecord":
        return TaskRecord(
            job_id=data.get("job_id", ""),
            status=data.get("status", "UNKNOWN"),
            local_fasta=data.get("local_fasta", ""),
            db_path=data.get("db_path", ""),
            task_type=data.get("task_type", ""),
            created_at=data.get("created_at", 0),
            task_dir=data.get("task_dir", ""),
            local_output=data.get("local_output", ""),
        )

    def get_created_time_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at))


class TaskManager:
    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or os.path.join(
            str(get_runtime_setting("local_output_dir", "") or ""),
            "task_history.json",
        )
        self.tasks: Dict[str, TaskRecord] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    record = TaskRecord.from_dict(item)
                    self.tasks[record.job_id] = record
            except Exception as e:
                print(f"加载任务历史失败: {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                data = [task.to_dict() for task in self.tasks.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存任务历史失败: {e}")

    def add_task(self, record: "TaskRecord"):
        self.tasks[record.job_id] = record
        self._save()

    def update_task_status(self, job_id: str, status: str, local_output: str = None):
        if job_id in self.tasks:
            self.tasks[job_id].status = status
            if local_output:
                self.tasks[job_id].local_output = local_output
            self._save()

    def get_task(self, job_id: str) -> Optional[TaskRecord]:
        return self.tasks.get(job_id)

    def get_all_tasks(self) -> List[TaskRecord]:
        return sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)

    def get_running_tasks(self) -> List[TaskRecord]:
        return [t for t in self.tasks.values() if t.status == "RUNNING"]

    def get_recent_tasks(self, limit: int = 10) -> List[TaskRecord]:
        return self.get_all_tasks()[:limit]

    def delete_task(self, job_id: str):
        if job_id in self.tasks:
            del self.tasks[job_id]
            self._save()

    def clear_old_tasks(self, days: int = 30):
        cutoff = time.time() - (days * 24 * 3600)
        to_delete = [
            job_id
            for job_id, task in self.tasks.items()
            if task.created_at < cutoff and task.status in ("DONE", "FAILED")
        ]
        for job_id in to_delete:
            del self.tasks[job_id]
        if to_delete:
            self._save()
        return len(to_delete)


_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
