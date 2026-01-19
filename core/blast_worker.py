# core/blast_worker.py
import os
import time
import uuid
from PyQt6.QtCore import QThread, pyqtSignal
from core.ssh_service import SSHService
from core.task_manager import get_task_manager, TaskRecord
from config import DEFAULT_CONFIG


class BlastWorker(QThread):
    """
    基于 screen 的异步 BLAST 任务调度器
    
    设计思想：
    - 解耦连接与执行：Windows 客户端仅负责"点火"和"观察"，Linux 服务器负责"执行"和"记录"
    - 状态文件化：通过远端 status.txt (RUNNING/DONE/FAILED) 和 task.log 传递任务进度
    - 轮询机制：客户端通过轻量级 SSH 命令定期检查状态文件
    """
    # 信号：成功标志, 提示信息, 本地结果文件路径
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)

    def __init__(self, client_provider, local_fasta, db_path, task, blast_bin, local_out_dir=None):
        super().__init__()
        self.client_provider = client_provider
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task = task
        self.blast_bin = blast_bin
        self.local_out_dir = local_out_dir or DEFAULT_CONFIG['local_output_dir']
        
        # 异步任务配置
        self.poll_interval = DEFAULT_CONFIG.get('poll_interval', 5)
        self.max_poll_retries = DEFAULT_CONFIG.get('max_poll_retries', 3)
        
        # 任务控制
        self._stop_requested = False
        self._job_id = None
        self._task_dir = None

    def request_stop(self):
        """请求停止任务"""
        self._stop_requested = True

    def get_job_id(self):
        """获取当前任务 ID"""
        return self._job_id

    def run(self):
        try:
            service = SSHService(self.client_provider)
            
            # === 第一阶段：前置检查与环境准备 ===
            self.progress.emit("🔍 正在检查远程环境...")
            
            # 检查 screen 是否安装
            if not self._check_screen_installed(service):
                self.finished.emit(False, "远端服务器未安装 screen，请先安装：sudo apt install screen", "")
                return
            
            # 生成唯一任务 ID 和目录
            self._job_id = f"blast_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            remote_dir = DEFAULT_CONFIG['remote_dir'].rstrip('/')
            self._task_dir = f"{remote_dir}/{self._job_id}"
            
            # 创建任务专属目录
            rc, _, err = service.run(f"mkdir -p {self._task_dir}", timeout=10)
            if rc != 0:
                raise Exception(f"创建任务目录失败: {err}")
            
            # === 第二阶段：上传文件并启动异步任务 ===
            filename = os.path.basename(self.local_fasta)
            remote_input = f"{self._task_dir}/input_{filename}"
            remote_output = f"{self._task_dir}/blast_result.out"
            status_file = f"{self._task_dir}/status.txt"
            log_file = f"{self._task_dir}/task.log"
            
            # 上传输入文件
            self.progress.emit("📤 正在上传序列文件...")
            service.upload(self.local_fasta, remote_input)
            
            # 构建 blastn 完整路径
            if self.blast_bin.endswith('/bin') or self.blast_bin.endswith('\\bin'):
                full_blast_cmd = f"{self.blast_bin.rstrip('/')}/blastn"
            else:
                full_blast_cmd = self.blast_bin
            
            # 获取远程脚本路径
            remote_script = DEFAULT_CONFIG.get('remote_script', '/home/zyserver/project/lzc_project/blast_runner.sh')
            
            # 检查远程脚本是否存在
            rc, _, _ = service.run(f"test -f {remote_script} && echo OK", timeout=10)
            if rc != 0:
                raise Exception(f"远程脚本不存在: {remote_script}\n请先将 blast_runner.sh 上传到 Linux 服务器")
            
            # 使用 screen 调用远程 sh 脚本
            # 脚本参数: <job_id> <input_file> <db_path> <task_type> <output_file> <blastn_path>
            self.progress.emit(f"🚀 正在启动远程 BLAST 任务 (ID: {self._job_id})...")
            screen_cmd = (
                f'screen -dmS {self._job_id} bash {remote_script} '
                f'{self._job_id} {remote_input} {self.db_path} {self.task} {remote_output} {full_blast_cmd}'
            )
            rc, _, err = service.run(screen_cmd, timeout=DEFAULT_CONFIG.get('screen_check_timeout', 10))
            if rc != 0:
                raise Exception(f"启动 screen 任务失败: {err}")
            
            # 保存任务记录到本地
            task_record = TaskRecord(
                job_id=self._job_id,
                status="RUNNING",
                local_fasta=self.local_fasta,
                db_path=self.db_path,
                task_type=self.task,
                task_dir=self._task_dir
            )
            get_task_manager().add_task(task_record)
            
            # === 第三阶段：状态轮询 ===
            self.progress.emit("⏳ 任务已提交，正在监控执行状态...")
            poll_failures = 0
            
            while not self._stop_requested:
                time.sleep(self.poll_interval)
                
                try:
                    status = self._check_task_status(service, status_file)
                    poll_failures = 0  # 重置失败计数
                    
                    if status == "RUNNING":
                        self.progress.emit(f"⏳ 任务执行中... (ID: {self._job_id})")
                        continue
                    elif status == "DONE":
                        self.progress.emit("✅ 远程任务完成，正在同步结果...")
                        break
                    elif status == "FAILED":
                        # 读取错误日志
                        _, log_content, _ = service.run(f"cat {log_file}", timeout=10)
                        raise Exception(f"BLAST 任务执行失败:\n{log_content}")
                    else:
                        # 状态未知，可能任务还在初始化
                        self.progress.emit(f"⏳ 等待任务启动... (状态: {status})")
                        
                except RuntimeError as e:
                    # SSH 连接异常，尝试重连
                    poll_failures += 1
                    if poll_failures >= self.max_poll_retries:
                        raise Exception(f"SSH 连接失败超过最大重试次数: {str(e)}")
                    self.progress.emit(f"⚠️ 连接异常，正在重试 ({poll_failures}/{self.max_poll_retries})...")
                    time.sleep(2)
            
            # 检查是否被手动停止
            if self._stop_requested:
                self._kill_remote_task(service)
                get_task_manager().update_task_status(self._job_id, "CANCELLED")
                self.finished.emit(False, "任务已被用户取消", "")
                return
            
            # === 第四阶段：结果同步与清理 ===
            os.makedirs(self.local_out_dir, exist_ok=True)
            local_out_path = os.path.join(self.local_out_dir, f"blast_res_{self._job_id}.txt")
            
            service.download(remote_output, local_out_path)
            
            # 更新任务状态为完成
            get_task_manager().update_task_status(self._job_id, "DONE", local_out_path)
            
            # 生成结果解读
            interpretation = self._generate_interpretation(local_out_path)
            
            # 可选：清理远程临时文件
            # service.run(f"rm -rf {self._task_dir}", timeout=10)
            
            self.finished.emit(True, f"分析完成！结果已同步至本地。\n任务ID: {self._job_id}", local_out_path)
            
        except Exception as e:
            # 更新任务状态为失败
            if self._job_id:
                get_task_manager().update_task_status(self._job_id, "FAILED")
            self.finished.emit(False, f"流程异常: {str(e)}", "")

    def _check_screen_installed(self, service: SSHService) -> bool:
        """检查远端是否安装了 screen"""
        try:
            rc, out, _ = service.run("command -v screen", timeout=10)
            return rc == 0 and out.strip() != ""
        except:
            return False

    def _check_task_status(self, service: SSHService, status_file: str) -> str:
        """检查任务状态"""
        rc, out, _ = service.run(f"cat {status_file} 2>/dev/null || echo UNKNOWN", timeout=10)
        return out.strip()

    def _kill_remote_task(self, service: SSHService):
        """终止远程任务"""
        if self._job_id:
            try:
                service.run(f"screen -S {self._job_id} -X quit", timeout=10)
                self.progress.emit(f"🛑 已终止远程任务: {self._job_id}")
            except:
                pass

    def _generate_interpretation(self, path):
        """简单的结果解读逻辑"""
        try:
            with open(path, 'r') as f:
                line = f.readline()
                if not line: return "未发现显著匹配项。"
                cols = line.strip().split('\t')
                return f"<b>最佳匹配：</b>{cols[1]}<br><b>一致性：</b>{cols[2]}%<br><b>E-value：</b>{cols[10]}"
        except:
            return "结果解析失败。"