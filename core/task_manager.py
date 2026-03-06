# core/task_manager.py
"""
[DEPRECATED] 任务历史管理器 (JSON 持久化)

已被 SQLite executions 表 + ExecutionHistoryCard 替代。
保留此文件供过渡期兼容，Phase 3 移除。
新代码请使用: DataRegistry + ToolEngine 的 ExecutionRecord。
"""
import os
import json
import time
from typing import List, Dict, Optional
from config import DEFAULT_CONFIG


class TaskRecord:
    """任务记录"""
    def __init__(self, job_id: str, status: str = "RUNNING", 
                 local_fasta: str = "", db_path: str = "", 
                 task_type: str = "", created_at: float = None,
                 task_dir: str = "", local_output: str = ""):
        self.job_id = job_id
        self.status = status  # RUNNING, DONE, FAILED, UNKNOWN
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task_type = task_type
        self.created_at = created_at or time.time()
        self.task_dir = task_dir  # 远程任务目录
        self.local_output = local_output  # 本地输出文件路径
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "local_fasta": self.local_fasta,
            "db_path": self.db_path,
            "task_type": self.task_type,
            "created_at": self.created_at,
            "task_dir": self.task_dir,
            "local_output": self.local_output
        }
    
    @staticmethod
    def from_dict(data: dict) -> 'TaskRecord':
        return TaskRecord(
            job_id=data.get("job_id", ""),
            status=data.get("status", "UNKNOWN"),
            local_fasta=data.get("local_fasta", ""),
            db_path=data.get("db_path", ""),
            task_type=data.get("task_type", ""),
            created_at=data.get("created_at", 0),
            task_dir=data.get("task_dir", ""),
            local_output=data.get("local_output", "")
        )
    
    def get_created_time_str(self) -> str:
        """获取格式化的创建时间"""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at))


class TaskManager:
    """任务管理器"""
    
    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or os.path.join(
            DEFAULT_CONFIG['local_output_dir'], 
            "task_history.json"
        )
        self.tasks: Dict[str, TaskRecord] = {}
        self._load()
    
    def _load(self):
        """从文件加载任务历史"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        record = TaskRecord.from_dict(item)
                        self.tasks[record.job_id] = record
            except Exception as e:
                print(f"加载任务历史失败: {e}")
    
    def _save(self):
        """保存任务历史到文件"""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                data = [task.to_dict() for task in self.tasks.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存任务历史失败: {e}")
    
    def add_task(self, record: TaskRecord):
        """添加新任务"""
        self.tasks[record.job_id] = record
        self._save()
    
    def update_task_status(self, job_id: str, status: str, local_output: str = None):
        """更新任务状态"""
        if job_id in self.tasks:
            self.tasks[job_id].status = status
            if local_output:
                self.tasks[job_id].local_output = local_output
            self._save()
    
    def get_task(self, job_id: str) -> Optional[TaskRecord]:
        """获取指定任务"""
        return self.tasks.get(job_id)
    
    def get_all_tasks(self) -> List[TaskRecord]:
        """获取所有任务，按创建时间倒序"""
        return sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)
    
    def get_running_tasks(self) -> List[TaskRecord]:
        """获取所有运行中的任务"""
        return [t for t in self.tasks.values() if t.status == "RUNNING"]
    
    def get_recent_tasks(self, limit: int = 10) -> List[TaskRecord]:
        """获取最近的任务"""
        all_tasks = self.get_all_tasks()
        return all_tasks[:limit]
    
    def delete_task(self, job_id: str):
        """删除任务记录"""
        if job_id in self.tasks:
            del self.tasks[job_id]
            self._save()
    
    def clear_old_tasks(self, days: int = 30):
        """清理指定天数前的已完成任务"""
        cutoff = time.time() - (days * 24 * 3600)
        to_delete = [
            job_id for job_id, task in self.tasks.items()
            if task.created_at < cutoff and task.status in ("DONE", "FAILED")
        ]
        for job_id in to_delete:
            del self.tasks[job_id]
        if to_delete:
            self._save()
        return len(to_delete)


# 全局单例
_task_manager: Optional[TaskManager] = None

def get_task_manager() -> TaskManager:
    """获取任务管理器单例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
