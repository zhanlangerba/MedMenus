import structlog, logging, os # type: ignore

ENV_MODE = os.getenv("ENV_MODE", "LOCAL")

# 根据环境设置默认日志级别
if ENV_MODE.upper() == "PRODUCTION":
    default_level = "WARNING"  # 生产环境只显示警告和错误
else:
    default_level = "INFO"  # 开发环境显示INFO级别及以上


# 直接设置为 INFO 级别来测试
LOGGING_LEVEL = logging.INFO

# 原来的逻辑（先注释掉测试）
# LOGGING_LEVEL = logging.getLevelNamesMapping().get(
#     os.getenv("LOGGING_LEVEL", default_level).upper(), 
#     logging.INFO  # 默认使用INFO级别
# )

# 根据环境选择渲染器
if ENV_MODE.lower() == "local":
    # 本地开发环境使用更友好的控制台输出
    renderer = [structlog.dev.ConsoleRenderer()]
else:
    # 其他环境使用JSON格式
    renderer = [structlog.processors.JSONRenderer()]

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.dict_tracebacks,
        # 临时注释掉 CallsiteParameterAdder 来隐藏 filename、func_name、lineno 等信息
        # structlog.processors.CallsiteParameterAdder(
        #     {
        #         structlog.processors.CallsiteParameter.FILENAME,
        #         structlog.processors.CallsiteParameter.FUNC_NAME,
        #         structlog.processors.CallsiteParameter.LINENO,
        #     }
        # ),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
        *renderer,
    ],
    cache_logger_on_first_use=True,
    wrapper_class=structlog.make_filtering_bound_logger(LOGGING_LEVEL),
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

# # Debug: Print actual configuration
# print(f"DEBUG Logger Config: ENV_MODE={ENV_MODE}, LOGGING_LEVEL={LOGGING_LEVEL}")
# print(f"DEBUG Logger Config: LOGGING_LEVEL numeric={LOGGING_LEVEL}")
# print(f"DEBUG Logger Config: INFO level={logging.INFO}")
# print(f"DEBUG Logger Config: Will INFO show? {LOGGING_LEVEL <= logging.INFO}")

# # Test logger immediately after configuration
# print("DEBUG: Testing logger immediately...")
# logger.info("DEBUG: This is a test INFO message from logger initialization")
# logger.warning("DEBUG: This is a test WARNING message from logger initialization")
# print("DEBUG: Logger test completed")
