"""Core 模块 — H2OMeta 核心功能。

保持包初始化轻量，避免仅导入 ``core`` 时触发 SSH / Paramiko 等重量级副作用。
"""
