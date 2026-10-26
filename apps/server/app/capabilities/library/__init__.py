"""教材库能力包。

有这个 `__init__.py` 才会被 `capabilities.discover()` 扫到——此前它缺失，
`library` 一直只是个普通的工具目录，迁移从未执行、能力也从未出现在导航里。
"""
