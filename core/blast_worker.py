# core/blast_worker.py
import os
import time
from PyQt6.QtCore import QThread, pyqtSignal
from core.ssh_service import SSHService
from config import DEFAULT_CONFIG

class BlastWorker(QThread):
    """处理远程 BLAST 执行与数据回传的后台线程"""
    # 信号：成功标志, 提示信息, 本地结果文件路径
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)

    def __init__(self, client_provider, local_fasta, db_path, task, blast_bin):
        super().__init__()
        self.client_provider = client_provider
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task = task
        self.blast_bin = blast_bin

    def run(self):
        try:
            service = SSHService(self.client_provider)
            
            # 1. 路径准备
            timestamp = int(time.time())
            filename = os.path.basename(self.local_fasta)
            remote_dir = DEFAULT_CONFIG['remote_dir'] # 远程临时目录
            remote_input = f"{remote_dir}/{timestamp}_{filename}".replace("\\", "/")
            remote_output = f"{remote_input}.out"
            
            # 本地输出路径：使用 config 中的 local_output_dir
            local_out_dir = DEFAULT_CONFIG['local_output_dir']
            local_out_path = os.path.join(local_out_dir, f"blast_res_{timestamp}.txt")

            # 2. 上传序列文件
            self.progress.emit(" 正在上传序列文件至服务器...")
            service.upload(self.local_fasta, remote_input)

            # 3. 远程执行 BLASTN
            self.progress.emit(f" 正在执行远程比对 ({self.task})...")
            # 使用 -outfmt 6 (表格格式) 并限制输出结果数量
            cmd = (f"{self.blast_bin} -query {remote_input} -db {self.db_path} "
                   f"-task {self.task} -out {remote_output} -outfmt 6 -max_target_seqs 10")
            
            rc, _, err = service.run(cmd, timeout=300)
            if rc != 0:
                self.finished.emit(False, f"执行失败: {err}", "")
                return

            # 4. 回传结果至本地 local_output_dir
            self.progress.emit(" 正在同步分析结果至本地...")
            service.download(remote_output, local_out_path)

            self.finished.emit(True, "分析完成！结果已成功同步至本地。", local_out_path)

        except Exception as e:
            self.finished.emit(False, f"流程异常: {str(e)}", "")