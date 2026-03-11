import json
import sys
from pathlib import Path

import paramiko

remote_dir = sys.argv[1]
config = json.loads(Path(r"E:\代码\bio_ui\.tmp_h2o_config.json").read_text(encoding="utf-8-sig"))
ssh_cfg = config.get("ssh", {})

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
kwargs = {
    "hostname": ssh_cfg.get("host", ""),
    "port": int(ssh_cfg.get("port", 22) or 22),
    "username": ssh_cfg.get("user", ""),
    "timeout": 10,
    "allow_agent": False,
    "look_for_keys": False,
}
if ssh_cfg.get("use_key") and ssh_cfg.get("key_file"):
    kwargs["key_filename"] = ssh_cfg["key_file"]
else:
    kwargs["password"] = ssh_cfg.get("password", "")

client.connect(**kwargs)
command = (
    f"echo '[LIST]'; ls -lah {remote_dir}; "
    f"echo '[HEAD]'; head -5 {remote_dir}/primer_result_final_2.txt 2>/dev/null; "
    f"echo '[COUNTS]'; wc -l {remote_dir}/primer_result.txt {remote_dir}/primer_result_final.txt {remote_dir}/primer_result_final_2.txt {remote_dir}/dimer_score.txt 2>/dev/null"
)
stdin, stdout, stderr = client.exec_command(command)
text = stdout.read().decode('utf-8', errors='ignore') + stderr.read().decode('utf-8', errors='ignore')
Path(r"E:\代码\bio_ui\.tmp_remote_show.txt").write_text(text, encoding='utf-8')
client.close()
print(Path(r"E:\代码\bio_ui\.tmp_remote_show.txt"))
