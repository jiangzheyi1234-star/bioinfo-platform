import pandas as pd
import requests
import time
from urllib.parse import quote
from PyQt6.QtCore import QThread, pyqtSignal

class AccessionWorker(QThread):
    """
    后台线程：根据用户指定的列（名称或TaxID）批量检索 NCBI Accession。
    支持多Sheet Excel文件处理，输出：原文件 + 3列新信息 (SciName, Link, Accession)
    """
    # 信号定义：进度条数值(int), 状态文字(str), 成功标志与路径(bool, str, str)
    progress_val = pyqtSignal(int)
    progress_msg = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, excel_path, target_col, api_key=""):
        """
        :param excel_path: Excel文件路径
        :param target_col: 用户在UI上选定的那一列的列名
        :param api_key: NCBI API Key (可选，用于加速)
        """
        super().__init__()
        self.excel_path = excel_path
        self.target_col = target_col
        self.api_key = api_key

    def get_ncbi_data(self, query_val):
        """核心查询逻辑 (NCBI Datasets API v2)"""
        # 1. 空值检查
        if not query_val or pd.isna(query_val) or str(query_val).strip() == "":
            return None, None, None

        # 2. URL 编码与构建
        safe_query = quote(str(query_val).strip())
        base_url = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon"
        headers = {"api-key": self.api_key} if self.api_key else {}
        request_url = f"{base_url}/{safe_query}/dataset_report"

        # 3. 三级降级策略：RefSeq Complete -> RefSeq -> GenBank
        search_strategies = [
            {"filters.assembly_source": "refseq", "filters.reference_only": "true"}, # 优先级1: 官方且完整
            {"filters.assembly_source": "refseq"},                                   # 优先级2: 官方任意级别
            {"filters.assembly_source": "genbank"}                                   # 优先级3: 第三方保底
        ]

        try:
            for strategy in search_strategies:
                # 响应用户取消
                if self.isInterruptionRequested(): 
                    return None, None, None
                
                params = {"page_size": 20, **strategy}
                # 发起请求
                response = requests.get(request_url, headers=headers, params=params, timeout=15)

                if response.status_code == 200:
                    data = response.json()
                    reports = data.get('reports', [])
                    if reports:
                        # --- 命中策略，开始择优 ---
                        
                        # A. 优先筛选完整基因组
                        complete = [r for r in reports if r.get('assembly_info', {}).get('assembly_level') == 'Complete Genome']
                        # 如果有完整的就用完整的，没有就用第一个（API默认排序质量最好的在前面）
                        best = complete[0] if complete else reports[0]

                        # B. 提取三项核心数据
                        # 1. 科学名称 (SciName)
                        sci_name = best.get('organism', {}).get('organism_name', 'N/A')
                        
                        # 2. 网页链接 (Link)
                        curr_acc = best.get('current_accession', '')
                        link = f"https://www.ncbi.nlm.nih.gov/datasets/genome/{curr_acc}" if curr_acc else ""

                        # 3. 核心 Accession (优先 Paired GCF, 其次 Current GCA)
                        paired = best.get("paired_accession", "")
                        if paired.startswith("GCF"): 
                            accession = paired
                        elif curr_acc: 
                            accession = curr_acc
                        else: 
                            accession = best.get("accession", "N/A")

                        # 只要找到，立即返回，不再执行后续低级策略
                        return sci_name, link, accession
            
            # 所有策略都跑完还没找到
            return "Not Found", "", ""

        except Exception as e:
            return f"Error: {str(e)}", "", ""

    def run(self):
        try:
            self.progress_msg.emit("正在读取 Excel 文件...")
            
            # 一次性读取所有sheets
            all_sheets = pd.read_excel(self.excel_path, sheet_name=None)
            
            total_sheets = len(all_sheets)
            processed_count = 0
            
            for sheet_name, df in all_sheets.items():
                self.progress_msg.emit(f"正在处理工作表: {sheet_name}")
                
                # 检查目标列是否存在于当前sheet
                if self.target_col not in df.columns:
                    self.progress_msg.emit(f"工作表 '{sheet_name}' 中未找到指定列 '{self.target_col}'，已跳过")
                    continue
                
                # 初始化 3 个新列 (如果已存在则会被覆盖/更新)
                new_cols = ["NCBI_SciName", "NCBI_Link", "NCBI_Accession"]
                for col in new_cols:
                    if col not in df.columns: 
                        df[col] = ""

                total_rows = len(df)
                
                # 遍历当前sheet的每一行
                for index, row in df.iterrows():
                    if self.isInterruptionRequested(): 
                        self.progress_msg.emit("操作已被取消")
                        return

                    # 获取目标列数据
                    val = row[self.target_col]
                    
                    # 更新状态栏
                    self.progress_msg.emit(f"处理 {sheet_name} [{index+1}/{total_rows}] 检索: {val}")

                    # 执行查询
                    sname, link, acc = self.get_ncbi_data(val)

                    # 回填数据
                    if sname: df.at[index, "NCBI_SciName"] = sname
                    if link: df.at[index, "NCBI_Link"] = link
                    if acc: df.at[index, "NCBI_Accession"] = acc

                    # 计算整体进度
                    overall_progress = int(((processed_count + (index + 1) / total_rows) / total_sheets) * 100)
                    self.progress_val.emit(overall_progress)
                    
                    # 频率控制
                    if not self.api_key:
                        time.sleep(0.34)

                # 当前sheet处理完成
                processed_count += 1
                self.progress_msg.emit(f"工作表 '{sheet_name}' 处理完成")

            # 保存结果
            out_path = self.excel_path.replace(".xlsx", "_filled.xlsx")
            self.progress_msg.emit("正在保存结果...")
            
            with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            self.finished.emit(True, "检索完成，结果已保存", out_path)

        except Exception as e:
            self.finished.emit(False, f"运行出错: {str(e)}", "")
        finally:
            # 确保资源被释放
            pass