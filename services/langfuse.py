import os
from langfuse import Langfuse

public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
secret_key = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

# 检查是否有有效的配置
enabled = bool(public_key and secret_key)

# 根据 langfuse 版本使用不同的初始化方式
try:
    if enabled:
        langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host
        )
    else:
        # 如果没有配置，创建一个禁用的实例
        langfuse = Langfuse(
            public_key="disabled",
            secret_key="disabled",
            host=host
        )
except TypeError:
    # 如果上面的方式失败，尝试旧版本的初始化方式
    try:
        langfuse = Langfuse(enabled=enabled)
    except TypeError:
        # 如果都失败，创建一个简单的占位符
        class DisabledLangfuse:
            def trace(self, *args, **kwargs):
                return self
            def span(self, *args, **kwargs):
                return self
            def end(self, *args, **kwargs):
                pass
        langfuse = DisabledLangfuse()
