"""异常层级：ReproAgentError → 各子系统子类。"""


class ReproAgentError(Exception):
    """所有 ReproAgent 业务异常的基类。"""


class ValidationError(ReproAgentError):
    """PDF 或输入校验失败。"""


class SchemaValidationError(ReproAgentError):
    """LLM 提取结果 schema 校验失败。"""


class ParseError(ReproAgentError):
    """研报解析（布局提取 / LLM 结构化）失败。"""


class ReproductionError(ReproAgentError):
    """因子计算或回测失败。"""


class DeviationError(ReproAgentError):
    """偏差分析或反思循环失败。"""


class LibraryError(ReproAgentError):
    """因子库注册 / 查询失败。"""


class CacheError(ReproAgentError):
    """缓存读写失败。"""


class PersistenceError(ReproAgentError):
    """数据库或文件系统持久化失败。"""


class ConfigurationError(ReproAgentError):
    """配置缺失或非法。"""


class LLMError(ParseError):
    """LLM 提取 / 修订失败（含生产环境禁止 mock）。"""


class FormulaError(ReproductionError):
    """因子公式解析或求值失败。"""
