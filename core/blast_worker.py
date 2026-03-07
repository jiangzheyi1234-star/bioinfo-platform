import os
import time
import uuid

from PyQt6.QtCore import QThread, pyqtSignal

from config import get_blast_setting, get_runtime_setting
from core.ssh_service import SSHService
from core.task_manager import TaskRecord, get_task_manager


class BlastWorker(QThread):
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)

    def __init__(self, client_provider, local_fasta, db_path, task, blast_bin, local_out_dir=None):
        super().__init__()
        self.client_provider = client_provider
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task = task
        self.blast_bin = blast_bin
        self.local_out_dir = local_out_dir or str(get_runtime_setting("local_output_dir", "") or "")
        self.poll_interval = int(get_runtime_setting("poll_interval", 5) or 5)
        self.max_poll_retries = int(get_runtime_setting("max_poll_retries", 3) or 3)
        self._stop_requested = False
        self._job_id = None
        self._task_dir = None

    def request_stop(self):
        self._stop_requested = True

    def get_job_id(self):
        return self._job_id

    def run(self):
        try:
            service = SSHService(self.client_provider)
            self.progress.emit("正在检查远程环境...")

            if not self._check_screen_installed(service):
                self.finished.emit(False, "远端服务器未安装 screen，请先安装：sudo apt install screen", "")
                return

            self._job_id = f"blast_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            remote_dir = str(get_blast_setting("remote_work_dir", "/tmp") or "/tmp").rstrip("/")
            self._task_dir = f"{remote_dir}/{self._job_id}"

            rc, _, err = service.run(f"mkdir -p {self._task_dir}", timeout=10)
            if rc != 0:
                raise Exception(f"创建任务目录失败: {err}")

            filename = os.path.basename(self.local_fasta)
            remote_input = f"{self._task_dir}/input_{filename}"
            remote_output = f"{self._task_dir}/blast_result.out"
            status_file = f"{self._task_dir}/status.txt"
            log_file = f"{self._task_dir}/task.log"

            self.progress.emit("正在上传序列文件...")
            service.upload(self.local_fasta, remote_input)

            if self.blast_bin.endswith("/bin") or self.blast_bin.endswith("\\bin"):
                full_blast_cmd = f"{self.blast_bin.rstrip('/')}/blastn"
            else:
                full_blast_cmd = self.blast_bin

            remote_script = str(
                get_blast_setting("remote_script", "/home/zyserver/project/lzc_project/blast_runner.sh")
                or "/home/zyserver/project/lzc_project/blast_runner.sh"
            )
            rc, _, _ = service.run(f"test -f {remote_script} && echo OK", timeout=10)
            if rc != 0:
                raise Exception(f"远程脚本不存在: {remote_script}\n请先将 blast_runner.sh 上传到 Linux 服务器")

            self.progress.emit(f"正在启动远程 BLAST 任务 (ID: {self._job_id})...")
            screen_cmd = (
                f"screen -dmS {self._job_id} bash {remote_script} "
                f"{self._job_id} {remote_input} {self.db_path} {self.task} {remote_output} {full_blast_cmd}"
            )
            rc, _, err = service.run(
                screen_cmd,
                timeout=int(get_runtime_setting("screen_check_timeout", 10) or 10),
            )
            if rc != 0:
                raise Exception(f"启动 screen 任务失败: {err}")

            task_record = TaskRecord(
                job_id=self._job_id,
                status="RUNNING",
                local_fasta=self.local_fasta,
                db_path=self.db_path,
                task_type=self.task,
                task_dir=self._task_dir,
            )
            get_task_manager().add_task(task_record)

            self.progress.emit("任务已提交，正在监控执行状态...")
            poll_failures = 0

            while not self._stop_requested:
                time.sleep(self.poll_interval)

                try:
                    status = self._check_task_status(service, status_file)
                    poll_failures = 0

                    if status == "RUNNING":
                        self.progress.emit(f"任务执行中... (ID: {self._job_id})")
                        continue
                    if status == "DONE":
                        self.progress.emit("远程任务完成，正在同步结果...")
                        break
                    if status == "FAILED":
                        _, log_content, _ = service.run(f"cat {log_file}", timeout=10)
                        raise Exception(f"BLAST 任务执行失败:\n{log_content}")

                    self.progress.emit(f"等待任务启动... (状态: {status})")
                except RuntimeError as e:
                    poll_failures += 1
                    if poll_failures >= self.max_poll_retries:
                        raise Exception(f"SSH 连接失败超过最大重试次数: {str(e)}")
                    self.progress.emit(f"连接异常，正在重试 ({poll_failures}/{self.max_poll_retries})...")
                    time.sleep(2)

            if self._stop_requested:
                self._kill_remote_task(service)
                get_task_manager().update_task_status(self._job_id, "CANCELLED")
                self.finished.emit(False, "任务已被用户取消", "")
                return

            os.makedirs(self.local_out_dir, exist_ok=True)
            local_out_path = os.path.join(self.local_out_dir, f"blast_res_{self._job_id}.txt")
            service.download(remote_output, local_out_path)

            get_task_manager().update_task_status(self._job_id, "DONE", local_out_path)
            self._generate_interpretation(local_out_path)
            self.finished.emit(True, f"分析完成，结果已同步至本地。\n任务ID: {self._job_id}", local_out_path)
        except Exception as e:
            if self._job_id:
                get_task_manager().update_task_status(self._job_id, "FAILED")
            self.finished.emit(False, f"流程异常: {str(e)}", "")

    def _check_screen_installed(self, service: SSHService) -> bool:
        try:
            rc, out, _ = service.run("command -v screen", timeout=10)
            return rc == 0 and out.strip() != ""
        except Exception:
            return False

    def _check_task_status(self, service: SSHService, status_file: str) -> str:
        rc, out, _ = service.run(f"cat {status_file} 2>/dev/null || echo UNKNOWN", timeout=10)
        return out.strip()

    def _kill_remote_task(self, service: SSHService):
        if self._job_id:
            try:
                service.run(f"screen -S {self._job_id} -X quit", timeout=10)
                self.progress.emit(f"已终止远程任务: {self._job_id}")
            except Exception:
                pass

    def _generate_interpretation(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                line = f.readline()
                if not line:
                    return "未发现显著匹配项。"
                cols = line.strip().split("\t")
                return f"<b>最佳匹配：</b>{cols[1]}<br><b>一致性：</b>{cols[2]}%<br><b>E-value：</b>{cols[10]}"
        except Exception:
            return "结果解析失败。"
