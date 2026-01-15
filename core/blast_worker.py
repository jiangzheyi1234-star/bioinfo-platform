# core/blast_worker.py
import os
import time
from PyQt6.QtCore import QThread, pyqtSignal
from core.ssh_service import SSHService
from config import DEFAULT_CONFIG

class BlastWorker(QThread):
    # 信号：成功标志, 提示信息, 本地结果文件路径, 解读信息
    finished = pyqtSignal(bool, str, str, str)
    progress = pyqtSignal(str)

    def __init__(self, client_provider, local_fasta, db_path, task, blast_bin, local_out_dir=None):
        super().__init__()
        self.client_provider = client_provider
        self.local_fasta = local_fasta
        self.db_path = db_path
        self.task = task
        self.blast_bin = blast_bin
        self.local_out_dir = local_out_dir or DEFAULT_CONFIG['local_output_dir']

    def run(self):
        try:
            service = SSHService(self.client_provider)
            timestamp = int(time.time())
            filename = os.path.basename(self.local_fasta)
            remote_dir = DEFAULT_CONFIG['remote_dir']
            remote_input = f"{remote_dir}/in_{timestamp}_{filename}".replace("\\", "/")
            remote_output = f"{remote_input}.out"
            
            # 使用传入的目录
            os.makedirs(self.local_out_dir, exist_ok=True)
            local_out_path = os.path.join(self.local_out_dir, f"blast_res_{timestamp}.txt")

            # 1. 上传
            self.progress.emit(" 正在上传序列文件...")
            service.upload(self.local_fasta, remote_input)

            # 2. 执行 (表格格式 outfmt 6)
            self.progress.emit(f" 正在执行远程比对 ({self.task})...")
            cmd = (f"{self.blast_bin} -query {remote_input} -db {self.db_path} "
                   f"-task {self.task} -out {remote_output} -outfmt 6 -max_target_seqs 50")
            rc, _, err = service.run(cmd, timeout=300)
            if rc != 0: raise Exception(err)

            # 3. 下载 (修正参数名为 remote_path)
            self.progress.emit(" 正在同步分析结果至本地...")
            service.download(remote_path=remote_output, local_path=local_out_path)

            # 4. 简单预解析用于解读
            interpretation = self._generate_interpretation(local_out_path)

            # 发射4个参数
            self.finished.emit(True, "分析完成！结果已同步至本地。", local_out_path, interpretation)
        except Exception as e:
            self.finished.emit(False, f"流程异常: {str(e)}", "", "")

    def _generate_interpretation(self, path):
        """简单的结果解读逻辑"""
        try:
            with open(path, 'r') as f:
                line = f.readline()
                if not line: return "未发现显著匹配项。"
                cols = line.strip().split('\t')
                # 生成紧凑的单行文本，避免HTML标签
                subject_id = (cols[1][:30] + '..') if len(cols[1]) > 30 else cols[1]  # 限制subject ID长度
                return f"最佳匹配: {subject_id}, 一致性: {cols[2]}%, E-value: {cols[10]}"
        except:
            return "结果解析失败。"