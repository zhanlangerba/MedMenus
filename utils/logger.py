import structlog, logging, os # type: ignore

ENV_MODE = os.getenv("ENV_MODE", "LOCAL")

# 根据环境设置默认日志级别
if ENV_MODE.upper() == "PRODUCTION":
    default_level = "WARNING"  # 生产环境只显示警告和错误
else:
    default_level = "WARNING"  # 开发环境也设置为警告级别，减少控制台输出

LOGGING_LEVEL = logging.getLevelNamesMapping().get(
    os.getenv("LOGGING_LEVEL", default_level).upper(), 
    logging.WARNING  # 默认使用WARNING级别
)

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
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
        *renderer,
    ],
    cache_logger_on_first_use=True,
    wrapper_class=structlog.make_filtering_bound_logger(LOGGING_LEVEL),
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()
