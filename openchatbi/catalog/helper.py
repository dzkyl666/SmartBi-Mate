"""数据库引擎创建工具（已移除 Trino/Presto token 服务，仅保留通用逻辑）。"""

from typing import Any

from sqlalchemy import Engine, create_engine

from openchatbi.utils import log


def create_sqlalchemy_engine_instance(data_warehouse_config: dict[str, Any]) -> Engine:
    """根据数据仓库配置创建 SQLAlchemy 引擎实例。

    Args:
        data_warehouse_config: 包含 'uri' 的配置字典

    Returns:
        配置好的 SQLAlchemy Engine
    """
    database_uri: str = data_warehouse_config.get("uri") or ""
    engine_args: dict[str, Any] = {"echo": False}

    log(f"Creating SQLAlchemy engine with URI: {database_uri[:50]}...")
    engine = create_engine(database_uri, **engine_args)
    return engine
