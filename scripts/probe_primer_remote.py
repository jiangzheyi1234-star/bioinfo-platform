import json
from pathlib import Path

import paramiko

config_path = Path(r"E:\代码\bio_ui\.tmp_h2o_config.json")
output_path = Path(r"E:\代码\bio_ui\.tmp_remote_probe.txt")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
ssh_cfg = config.get("ssh", {})
remote_dir = "/home/zyserver/project_ssd/primer_design/my_result"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
connect_kwargs = {
    "hostname": ssh_cfg.get("host", ""),
    "port": int(ssh_cfg.get("port", 22) or 22),
    "username": ssh_cfg.get("user", ""),
    "timeout": 8,
    "allow_agent": False,
    "look_for_keys": False,
}
if ssh_cfg.get("use_key") and ssh_cfg.get("key_file"):
    connect_kwargs["key_filename"] = ssh_cfg["key_file"]
else:
    connect_kwargs["password"] = ssh_cfg.get("password", "")

client.connect(**connect_kwargs)
command = (
    f"echo '[PWD]'; pwd; "
    f"echo '[LIST]'; ls -lah {remote_dir}; "
    f"echo '[HEAD]'; head -5 {remote_dir}/primer_result_final_2.txt 2>/dev/null; "
    f"echo '[COUNTS]'; "
    f"wc -l {remote_dir}/primer_result.txt {remote_dir}/primer_result_final.txt {remote_dir}/primer_result_final_2.txt {remote_dir}/dimer_score.txt 2>/dev/null"
)
stdin, stdout, stderr = client.exec_command(command)
content = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
output_path.write_text(content, encoding="utf-8")
client.close()
print(output_path)
