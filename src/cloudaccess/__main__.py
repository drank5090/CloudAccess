"""``python -m cloudaccess`` 与 PyInstaller 打包的入口。

注意：必须使用绝对导入——PyInstaller 会把本文件作为顶层脚本执行，
此时不存在包上下文，相对导入会失败。
"""

from cloudaccess.app import main

if __name__ == "__main__":
    raise SystemExit(main())
