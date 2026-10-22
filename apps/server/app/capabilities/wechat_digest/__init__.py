"""群聊简报（wechat_digest）能力。

目录结构见 ``docs/WECHAT-DIGEST.md`` §1：

- ``capability.py``：manifest / 路由 / 迁移 / 工具 / 任务注册
- ``router.py``：``/api/c/wechat_digest/*`` 接口
- ``models.py``：``wechat_digests`` 表映射
- ``jobs.py``：后台任务
- ``service.py``：解析 / 清洗 / 落库 / 导出的可复用逻辑
- ``sources/``：数据源适配器（目前只有粘贴文本）
- ``pipeline/``：清洗、提示词、Map-Reduce 总结、导出
- ``migrations/``：建表 SQL
"""
