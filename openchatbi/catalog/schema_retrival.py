"""Schema and column retrieval functionality for finding relevant database structures."""

import os
import re

import Levenshtein

from openchatbi import config
from openchatbi.catalog.retrival_helper import build_column_tables_mapping, build_columns_retriever
from openchatbi.text_segmenter import _segmenter
from openchatbi.utils import log

# Skip build during documentation build
# 延迟初始化：模块导入时 config 可能还没加载，
# 改为首次调用时才构建检索器，避免空 mapping 问题。
_bm25 = None
_vector_db = None
_columns = None
_col_dict = None
_column_tables_mapping = None


def _ensure_initialized():
    """确保检索器已初始化（懒加载）。"""
    global _bm25, _vector_db, _columns, _col_dict, _column_tables_mapping
    if _column_tables_mapping is not None:
        return
    if os.environ.get("SPHINX_BUILD"):
        _bm25, _vector_db, _columns, _col_dict = None, None, [], {}
        _column_tables_mapping = {}
        return
    try:
        _catalog_store = config.get().catalog_store
    except ValueError:
        _catalog_store = None
    if _catalog_store:
        _bm25, _vector_db, _columns, _col_dict = build_columns_retriever(
            _catalog_store, config.get().vector_db_path
        )
        _column_tables_mapping = build_column_tables_mapping(_catalog_store)
    else:
        _bm25, _vector_db, _columns, _col_dict = None, None, [], {}
        _column_tables_mapping = {}


# 提供与原代码兼容的模块级访问接口
class _LazyProxy:
    """代理对象，首次访问时触发初始化。"""
    def __init__(self, attr_name):
        self._attr = attr_name
    def __getattr__(self, name):
        _ensure_initialized()
        val = globals()[self._attr]
        return getattr(val, name)
    def __iter__(self):
        _ensure_initialized()
        return iter(globals()[self._attr])
    def __len__(self):
        _ensure_initialized()
        return len(globals()[self._attr])
    def __bool__(self):
        _ensure_initialized()
        return bool(globals()[self._attr])
    def __getitem__(self, key):
        _ensure_initialized()
        return globals()[self._attr][key]
    def get(self, key, default=None):
        _ensure_initialized()
        return globals()[self._attr].get(key, default)


bm25 = _LazyProxy("_bm25")
vector_db = _LazyProxy("_vector_db")
columns = _LazyProxy("_columns")
col_dict = _LazyProxy("_col_dict")
column_tables_mapping = _LazyProxy("_column_tables_mapping")


def column_retrieval(query, db, k=10, threshold=0.5, filter=None):
    """Retrieves relevant columns based on a similarity search.

    Args:
        query (str): The query string to search for.
        db: The vector database to search in.
        k (int, optional): The number of top results to return. Defaults to 10.
        threshold (float, optional): The similarity threshold for filtering results. Defaults to 0.5.
        filter (dict, optional): A filter to apply to the search. Defaults to None.

    Returns:
        list: List of relevant column names.
    """
    log(f"Get the top relevant columns for query: {query}")
    # embedding 端点间歇性 400（百炼 text-embedding-v4 ~25% 概率 InternalError），
    # 此处加 try/except + 重试，避免直接上抛把整个 agent graph 搞崩。
    # 三次都失败时返回空列表——上游 get_relevant_columns 的 BM25/编辑距离
    # 不依赖 embedding，空向量结果不影响整体检索。
    import time as _time
    last_err = None
    for attempt in range(3):
        try:
            similar_column_key_scores = db.similarity_search_with_score(query, k=k, filter=filter)
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                _time.sleep(0.5 * (attempt + 1))
    else:
        log(f"WARN: 向量检索连续失败，BM25/编辑距离兜底: {last_err}")
        return []
    # log(f"similar_column_key_scores: {similar_column_key_scores}")
    column_names = [key.metadata["column_name"] for (key, score) in similar_column_key_scores if score < threshold]
    log(f"Filtered relevant columns: {column_names}")
    return column_names


def merge_list(list1, list2):
    return list(set(list1 + list2))


def edit_distance_score(key1, key2):
    """Calculate normalized edit distance score between two strings.

    Returns:
        float: Score between 0 (identical) and 1 (completely different).
    """
    dist = Levenshtein.distance(key1, key2)
    max_len = max(len(key1), len(key2))
    return dist / max_len if max_len > 0 else 1


def edit_distance_search(keywords_list, top_k=10, threshold=0.5):
    """Searches for columns using edit distance similarity.

    Args:
        keywords_list (list): List of keywords to search for.
        top_k (int, optional): The number of top results to return per keyword. Defaults to 10.
        threshold (float, optional): The maximum edit distance score to consider. Defaults to 0.5.

    Returns:
        list: List of relevant column names.
    """
    keys = {re.sub(r"(_id|_name| id| name)$", "", key.lower()) for key in keywords_list}
    column_similarity_score = set()
    for key in keys:
        key_column_similarity_score = {}
        for column_name, row in col_dict.items():
            column_name_score = edit_distance_score(
                key, re.sub(r"(_id|_name| id| name)$", "", row.get("column_name", ""))
            )
            display_score = edit_distance_score(
                key, re.sub(r"(_id|_name| id| name)$", "", row.get("display_name", "").lower())
            )
            if column_name_score < threshold or display_score < threshold:
                key_column_similarity_score[column_name] = min(column_name_score, display_score)
        key_top_column = [
            key for key, _ in sorted(key_column_similarity_score.items(), key=lambda x: x[1], reverse=True)[:top_k]
        ]
        column_similarity_score.update(key_top_column)
    return list(column_similarity_score)


def bm25_search(query_list, top_k=5, score_threshold=0.5):
    """Performs a BM25 search on columns based on the query.

    Args:
        query_list (list): List of query terms.
        top_k (int, optional): The number of top results to return. Defaults to 5.
        score_threshold (float, optional): The minimum BM25 score to consider. Defaults to 0.5.

    Returns:
        list: List of relevant column names.
    """
    query_tokens = [token for token in _segmenter.cut(" ".join(query_list)) if token not in ("_", " ")]
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = []
    for idx, score in ranked[:top_k]:
        if score_threshold and score < score_threshold:
            continue
        results.append(columns[idx]["column_name"])
    return results


def get_relevant_columns(keywords_list, dimensions, metrics):
    """Get the most relevant columns for given keywords, dimensions, and metrics.

    Uses multiple retrieval methods (BM25, edit distance, vector similarity)
    to find the best matching columns.

    Args:
        keywords_list (list): General keywords to search for.
        dimensions (list): Dimension-specific keywords.
        metrics (list): Metric-specific keywords.

    Returns:
        list: Relevant column names.
    """
    # 1. BM25 search for general keywords
    total_results = bm25_search(keywords_list, top_k=len(keywords_list) * 4)

    # 2. Edit distance search for exact matches
    keyword_len = len(keywords_list + dimensions + metrics)
    ed_results = edit_distance_search(keywords_list + dimensions + metrics, top_k=keyword_len, threshold=0.3)
    total_results = merge_list(total_results, ed_results)

    # 3. Vector similarity search for dimensions
    if dimensions:
        d_results = column_retrieval(" ".join(dimensions), vector_db, k=10, filter={"category": "dimension"})
        total_results = merge_list(total_results, d_results)

    # 4. Vector similarity search for metrics
    if metrics:
        m_results = column_retrieval(" ".join(metrics), vector_db, k=10, threshold=0.55, filter={"category": "metric"})
        total_results = merge_list(total_results, m_results)

    log(f"Relevant columns: {total_results}")
    return total_results
