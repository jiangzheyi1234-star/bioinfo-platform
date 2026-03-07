import time

from PyQt6.QtCore import QThread, pyqtSignal

from config import get_blast_setting
from core.ssh_service import SSHService


class DbBuilderWorker(QThread):
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)

    def __init__(self, client_provider, local_fasta, db_name):
        super().__init__()
        self.client_provider = client_provider
        self.local_fasta = local_fasta
        self.db_name = db_name

    def run(self):
        try:
            service = SSHService(self.client_provider)
            ts = int(time.time())

            remote_work_dir = str(get_blast_setting("remote_work_dir", "/tmp") or "/tmp")
            remote_db_dir = f"{remote_work_dir}/custom_dbs/{self.db_name}_{ts}"
            remote_fasta = f"{remote_db_dir}/source.fasta"

            service.run(f"mkdir -p {remote_db_dir}")

            self.progress.emit("正在上传序列文件...")
            service.upload(self.local_fasta, remote_fasta)

            self.progress.emit("正在服务器上构建索引 (makeblastdb)...")
            db_path_prefix = f"{remote_db_dir}/{self.db_name}"
            cmd = f"makeblastdb -in {remote_fasta} -dbtype nucl -out {db_path_prefix} -title '{self.db_name}'"
            rc, _, err = service.run(cmd, timeout=600)
            if rc != 0:
                raise Exception(f"构建失败: {err}")

            self.finished.emit(True, f"数据库 '{self.db_name}' 构建成功", db_path_prefix)
        except Exception as e:
            self.finished.emit(False, f"建库流程异常: {str(e)}", "")
