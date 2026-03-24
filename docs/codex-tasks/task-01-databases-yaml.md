# Task 1: databases.yaml 路径相对化 + 分类字段

## 目标
修改 `plugins/databases.yaml`，将所有绝对路径改为相对路径，新增 category 分类字段，模板化 install_cmd。

## 修改文件
`plugins/databases.yaml`

## 具体要求

### 1. install_path 改为相对路径
所有 `install_path` 从绝对路径改为相对于 `db_root` 的相对路径。只保留最后一级或两级目录名。

示例：
```yaml
# 改前
kraken2_standard:
  install_path: "/home/zyserver/project_ssd/common_data/kraken2_standard"

# 改后
kraken2_standard:
  install_path: "kraken2_standard"
```

完整映射表：
| 数据库 ID | 改前 install_path | 改后 install_path |
|---|---|---|
| kraken2_standard | /home/zyserver/project_ssd/common_data/kraken2_standard | kraken2_standard |
| kraken2_plusPFP | /h2ometa/databases/kraken2_plusPFP | kraken2_plusPFP |
| blast_nt | /home/zyserver/project_ssd/common_data/core_nt_database/core_nt | blast_nt |
| core_nt | /home/zyserver/project_ssd/common_data/core_nt_database | core_nt |
| centrifuge_hpvc | /home/zyserver/project/lcy_project/my_database/hpvc | "" (保持空，builtin) |
| checkm2_db | /h2ometa/databases/checkm2 | checkm2 |
| gtdb_r220 | /h2ometa/databases/gtdbtk/release220 | gtdbtk/release220 |
| busco_bacteria | /h2ometa/databases/busco/bacteria_odb10 | busco/bacteria_odb10 |
| bakta_db | /h2ometa/databases/bakta/db | bakta/db |
| bakta_db_light | /h2ometa/databases/bakta/db-light | bakta/db-light |
| eggnog_db | /h2ometa/databases/eggnog | eggnog |
| card_db | /h2ometa/databases/card | card |
| amrfinder_db | /h2ometa/databases/amrfinder | amrfinder |
| gunc_db | /h2ometa/databases/gunc | gunc |
| metaphlan_db | /h2ometa/databases/metaphlan | metaphlan |
| genomad_db | /h2ometa/databases/genomad | genomad |
| hostile_human_t2t | "" | "" (保持空，builtin) |

### 2. 新增 category 字段
每个数据库条目新增 `category` 字段，值为以下之一：

| category | 数据库 |
|---|---|
| reads | kraken2_standard, kraken2_plusPFP, blast_nt, core_nt, centrifuge_hpvc, metaphlan_db |
| mag | checkm2_db, gtdb_r220, busco_bacteria, gunc_db |
| annotation | bakta_db, bakta_db_light, eggnog_db |
| amr | card_db, amrfinder_db |
| other | genomad_db, hostile_human_t2t |

放在 `description` 字段之后。

### 3. install_cmd 模板化
将 install_cmd 中的硬编码路径替换为 `{{ db_path }}` Jinja2 变量：

```yaml
# card_db 改前
install_cmd: "rgi load --card_json /h2ometa/databases/card/card.json --local"
# 改后
install_cmd: "rgi load --card_json {{ db_path }}/card.json --local"

# amrfinder_db 改前
install_cmd: "amrfinder_update --force_update --database /h2ometa/databases/amrfinder"
# 改后
install_cmd: "amrfinder_update --force_update --database {{ db_path }}"

# genomad_db 改前
install_cmd: "genomad download-database /h2ometa/databases/genomad"
# 改后
install_cmd: "genomad download-database {{ db_path }}"
```

### 4. 不动的部分
- `builtin: true` 的数据库（hostile_human_t2t、centrifuge_hpvc）保持 `install_path: ""` 不变
- 所有其他字段（name, description, size_mb, tools, mirrors, integrity_check, env_var）不变
- YAML 注释和分组结构保持不变

## 验证
- YAML 语法正确（`python -c "import yaml; yaml.safe_load(open('plugins/databases.yaml'))"`）
- 所有非 builtin 数据库都有 `category` 字段
- 所有 `install_path` 不包含 `/home/` 或 `/h2ometa/` 前缀
- install_cmd 中不包含绝对路径
