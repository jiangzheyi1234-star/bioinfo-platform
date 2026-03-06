# core/task_recovery_worker.py
"""
[DEPRECATED] 任务恢复 Worker

已被 JobMonitor + RetryManager 替代。
保留此文件供过渡期兼容，Phase 3 移除。
新代码请使用: JobMonitor 自动轮询 + RetryManager 自动重试。
"""
import os
import time
from PyQt6.QtCore import QThread, pyqtSignal
from core.ssh_service import SSHService
from core.task_manager import get_task_manager, TaskRecord
from config import DEFAULT_CONFIG


class TaskRecoveryWorker(QThread):
    """
    任务恢复 Worker
    用于检查之前运行中的任务状态，并下载已完成的结果
    """
    # 信号：job_id, 新状态, 消息, 本地文件路径(如果完成)
    task_updated = pyqtSignal(str, str, str, str)
    # 所有任务检查完成
    all_checked = pyqtSignal(int, int, int)  # 总数, 完成数, 失败数
    progress = pyqtSignal(str)

    def __init__(self, client_provider, tasks_to_check: list = None):
        super().__init__()
        self.client_provider = client_provider
        self.tasks_to_check = tasks_to_check  # 如果为 None，则检查所有 RUNNING 状态的任务
        self.local_out_dir = DEFAULT_CONFIG['local_output_dir']

    def run(self):
        try:
            service = SSHService(self.client_provider)
            task_manager = get_task_manager()
            
            # 获取需要检查的任务
            if self.tasks_to_check is None:
                tasks = task_manager.get_running_tasks()
            else:
                tasks = [task_manager.get_task(job_id) for job_id in self.tasks_to_check]
                tasks = [t for t in tasks if t is not None]
            
            if not tasks:
                self.progress.emit("没有需要检查的任务")
                self.all_checked.emit(0, 0, 0)
                return
            
            self.progress.emit(f"正在检查 {len(tasks)} 个任务的状态...")
            
            done_count = 0
            failed_count = 0
            
            for task in tasks:
                try:
                    self.progress.emit(f"检查任务: {task.job_id}")
                    
                    status_file = f"{task.task_dir}/status.txt"
                    log_file = f"{task.task_dir}/task.log"
                    remote_output = f"{task.task_dir}/blast_result.out"
                    
                    # 检查状态
                    rc, status, _ = service.run(f"cat {status_file} 2>/dev/null || echo UNKNOWN", timeout=10)
                    status = status.strip()
                    
                    if status == "DONE":
                        # 下载结果
                        os.makedirs(self.local_out_dir, exist_ok=True)
                        local_out_path = os.path.join(self.local_out_dir, f"blast_res_{task.job_id}.txt")
                        
                        try:
                            service.download(remote_output, local_out_path)
                            task_manager.update_task_status(task.job_id, "DONE", local_out_path)
                            self.task_updated.emit(task.job_id, "DONE", "任务已完成，结果已下载", local_out_path)
                            done_count += 1
                        except Exception as e:
                            task_manager.update_task_status(task.job_id, "FAILED")
                            self.task_updated.emit(task.job_id, "FAILED", f"下载结果失败: {e}", "")
                            failed_count += 1
                            
                    elif status == "FAILED":
                        # 读取日志
                        _, log_content, _ = service.run(f"cat {log_file} 2>/dev/null", timeout=10)
                        task_manager.update_task_status(task.job_id, "FAILED")
                        self.task_updated.emit(task.job_id, "FAILED", f"任务失败:\n{log_content[:500]}", "")
                        failed_count += 1
                        
                    elif status == "RUNNING":
                        # 仍在运行
                        self.task_updated.emit(task.job_id, "RUNNING", "任务仍在运行中", "")
                        
                    else:
                        # 状态未知，可能任务目录已被清理
                        task_manager.update_task_status(task.job_id, "UNKNOWN")
                        self.task_updated.emit(task.job_id, "UNKNOWN", "无法获取任务状态，可能已被清理", "")
                        
                except Exception as e:
                    self.task_updated.emit(task.job_id, "ERROR", f"检查失败: {str(e)}", "")
            
            self.progress.emit(f"检查完成: {done_count} 个已完成, {failed_count} 个失败")
            self.all_checked.emit(len(tasks), done_count, failed_count)
            
        except Exception as e:
            self.progress.emit(f"检查任务时出错: {str(e)}")
            self.all_checked.emit(0, 0, 0)


class SingleTaskMonitorWorker(QThread):
    """
    单个任务监控 Worker
    用于继续监控某个 RUNNING 状态的任务
    """
    finished = pyqtSignal(bool, str, str)  # 成功?, 消息, 本地文件路径
    progress = pyqtSignal(str)

    def __init__(self, client_provider, job_id: str):
        super().__init__()
        self.client_provider = client_provider
        self.job_id = job_id
        self._stop_requested = False
        self.poll_interval = DEFAULT_CONFIG.get('poll_interval', 5)
        self.max_poll_retries = DEFAULT_CONFIG.get('max_poll_retries', 3)
        self.local_out_dir = DEFAULT_CONFIG['local_output_dir']

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            service = SSHService(self.client_provider)
            task_manager = get_task_manager()
            
            task = task_manager.get_task(self.job_id)
            if not task:
                self.finished.emit(False, f"找不到任务: {self.job_id}", "")
                return
            
            status_file = f"{task.task_dir}/status.txt"
            log_file = f"{task.task_dir}/task.log"
            remote_output = f"{task.task_dir}/blast_result.out"
            
            self.progress.emit(f"⏳ 继续监控任务: {self.job_id}")
            poll_failures = 0
            
            while not self._stop_requested:
                time.sleep(self.poll_interval)
                
                try:
                    rc, status, _ = service.run(f"cat {status_file} 2>/dev/null || echo UNKNOWN", timeout=10)
                    status = status.strip()
                    poll_failures = 0
                    
                    if status == "RUNNING":
                        self.progress.emit(f"⏳ 任务执行中... (ID: {self.job_id})")
                        continue
                    elif status == "DONE":
                        self.progress.emit("✅ 远程任务完成，正在同步结果...")
                        break
                    elif status == "FAILED":
                        _, log_content, _ = service.run(f"cat {log_file}", timeout=10)
                        task_manager.update_task_status(self.job_id, "FAILED")
                        self.finished.emit(False, f"BLAST 任务执行失败:\n{log_content}", "")
                        return
                    else:
                        self.progress.emit(f"⏳ 等待任务... (状态: {status})")
                        
                except RuntimeError as e:
                    poll_failures += 1
                    if poll_failures >= self.max_poll_retries:
                        self.finished.emit(False, f"SSH 连接失败: {str(e)}", "")
                        return
                    self.progress.emit(f"⚠️ 连接异常，正在重试...")
                    time.sleep(2)
            
            if self._stop_requested:
                self.finished.emit(False, "监控已停止", "")
                return
            
            # 下载结果
            os.makedirs(self.local_out_dir, exist_ok=True)
            local_out_path = os.path.join(self.local_out_dir, f"blast_res_{self.job_id}.txt")
            service.download(remote_output, local_out_path)
            
            task_manager.update_task_status(self.job_id, "DONE", local_out_path)
            self.finished.emit(True, f"分析完成！结果已同步至本地。\n任务ID: {self.job_id}", local_out_path)
            
        except Exception as e:
            self.finished.emit(False, f"监控异常: {str(e)}", "")
