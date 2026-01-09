"""嵌入模型连通性测试脚本。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# 确保可以导入 src 下的 app 包
ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.core.settings import get_settings  # noqa: E402
from app.integrations.embedding_client import EmbeddingClient  # noqa: E402


async def main() -> None:
    settings = get_settings()
    client = EmbeddingClient()

    samples = [
        "这是一条用于验证向量嵌入接口的测试文本。",
        "第二条测试文本，用于检查批量输入是否工作正常。",
    ]

    print(f"使用模型: {settings.embedding_model}")
    print(f"基地址: {settings.embedding_base_url}")
    print("将发送 2 条测试文本，超时 30 秒\n")

    start = time.perf_counter()
    try:
        vectors = await client.embed(texts=samples, timeout_seconds=30.0)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        print(f"调用失败，耗时 {elapsed_ms} ms，错误: {exc}")
        return

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    if not vectors:
        print("调用成功但返回为空，请检查服务日志。")
        return

    dim = len(vectors[0])
    expected_dim = settings.embedding_dim

    print(f"共返回 {len(vectors)} 条向量，耗时 {elapsed_ms} ms，维度={dim}")
    if expected_dim:
        status = "匹配" if dim == expected_dim else "不匹配"
        print(f"期望维度={expected_dim}，{status}")
    print(f"第一条向量前 8 维: {vectors[0][:8]}")


if __name__ == "__main__":
    asyncio.run(main())
