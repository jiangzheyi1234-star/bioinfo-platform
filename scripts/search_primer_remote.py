import json
from pathlib import Path

import paramiko

config_path = Path(r"E:\代码\bio_ui\.tmp_h2o_config.json")
output_path = Path(r"E:\代码\bio_ui\.tmp_remote_search.txt")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
ssh_cfg = config.get("ssh", {})

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
connect_kwargs = {
    "hostname": ssh_cfg.get("host", ""),
    "port": int(ssh_cfg.get("port", 22) or 22),
    "username": ssh_cfg.get("user", ""),
    "timeout": 12,
    "allow_agent": False,
    "look_for_keys": False,
}
if ssh_cfg.get("use_key") and ssh_cfg.get("key_file"):
    connect_kwargs["key_filename"] = ssh_cfg["key_file"]
else:
    connect_kwargs["password"] = ssh_cfg.get("password", "")

client.connect(**connect_kwargs)
command = r"""
echo '[PRIMER_DESIGN_DIRS]'
find /home/zyserver -maxdepth 4 -type d \( -name 'primer_design' -o -name 'my_result' \) 2>/dev/null | head -100
echo '[RESULT_FILES]'
find /home/zyserver -type f -name 'primer_result_final_2.txt' 2>/dev/null | head -100
echo '[AUTO_RUN]'
find /home/zyserver -type f -name '0_auto_run.sh' 2>/dev/null | head -50
"""
stdin, stdout, stderr = client.exec_command(command)
content = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
output_path.write_text(content, encoding="utf-8")
client.close()
print(output_path)
