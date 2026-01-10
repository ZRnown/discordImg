import faiss
import numpy as np
import os
import pickle
import logging
from typing import List, Dict, Tuple
from config import config

logger = logging.getLogger(__name__)

class VectorEngine:
    """
    FAISS HNSW向量搜索引擎
    纯文件系统存储，无需Docker
    支持百万级向量毫秒级查询
    """

    def __init__(self, index_file=None, id_map_file=None):
        self.index_file = index_file or config.FAISS_INDEX_FILE
        self.id_map_file = id_map_file or config.FAISS_ID_MAP_FILE

        self.dimension = config.VECTOR_DIMENSION
        self.index = None

        # FAISS只能存整数ID，我们需要一个映射：FAISS内部ID -> 数据库(product_images表的ID)
        # 这个列表的索引是FAISS ID，值是数据库ID
        self.id_map = []

        self._load_or_create_index()

    def _load_or_create_index(self):
        """加载或创建FAISS HNSW索引"""
        if os.path.exists(self.index_file) and os.path.exists(self.id_map_file):
            logger.info("正在加载FAISS索引...")
            try:
                self.index = faiss.read_index(self.index_file)
                with open(self.id_map_file, 'rb') as f:
                    self.id_map = pickle.load(f)
                logger.info(f"✅ FAISS索引加载完成，当前包含 {self.index.ntotal} 个向量")
            except Exception as e:
                logger.error(f"加载索引失败，将创建新索引: {e}")
                self._create_new_index()
        else:
            logger.info("创建新的FAISS HNSW索引...")
            self._create_new_index()

    def _create_new_index(self):
        """创建新的FAISS HNSW索引"""
        # HNSW64: 图结构，查询极快，准确率高
        # InnerProduct (IP) 在归一化向量上等同于余弦相似度
        self.index = faiss.IndexHNSWFlat(
            self.dimension,
            config.FAISS_HNSW_M,
            faiss.METRIC_INNER_PRODUCT
        )

        # 设置构建参数
        self.index.efConstruction = config.FAISS_EF_CONSTRUCTION  # 构建时的深度，越高越准但构建越慢
        self.index.efSearch = config.FAISS_EF_SEARCH             # 搜索时的深度

        self.id_map = []

        # 确保目录存在
        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)

    def save(self):
        """保存索引到磁盘 (百万级数据保存大约需要几秒)"""
        try:
            faiss.write_index(self.index, self.index_file)
            with open(self.id_map_file, 'wb') as f:
                pickle.dump(self.id_map, f)
            logger.info("FAISS索引已保存到磁盘")
        except Exception as e:
            logger.error(f"保存索引失败: {e}")

    def add_vector(self, db_id: int, vector: np.ndarray) -> bool:
        """添加向量到FAISS索引"""
        try:
            # 确保向量是正确的形状和类型
            if isinstance(vector, list):
                vector = np.array(vector, dtype='float32')
            elif vector.dtype != np.float32:
                vector = vector.astype('float32')

            vector = vector.reshape(1, -1)  # 确保是[1, dim]形状

            # 添加到FAISS
            self.index.add(vector)

            # 记录ID映射：FAISS内部ID -> 数据库ID
            faiss_id = self.index.ntotal - 1  # 新添加的向量ID
            if len(self.id_map) <= faiss_id:
                self.id_map.extend([None] * (faiss_id - len(self.id_map) + 1))
            self.id_map[faiss_id] = db_id

            return True

        except Exception as e:
            logger.error(f"添加向量失败: {e}")
            return False

    def search(self, query_vector: np.ndarray, top_k: int = 1) -> List[Dict]:
        """搜索最相似的向量"""
        if self.index.ntotal == 0:
            return []

        try:
            # 确保查询向量格式正确
            if isinstance(query_vector, list):
                query_vector = np.array(query_vector, dtype='float32')
            elif query_vector.dtype != np.float32:
                query_vector = query_vector.astype('float32')

            query_vector = query_vector.reshape(1, -1)

            # 执行搜索
            # distances: 相似度分数 (因为是内积且归一化了，范围-1到1)
            # indices: FAISS内部的ID
            distances, indices = self.index.search(query_vector, top_k)

            results = []
            for i in range(min(top_k, len(indices[0]))):
                faiss_id = indices[0][i]
                score = distances[0][i]

                if faiss_id != -1 and faiss_id < len(self.id_map) and self.id_map[faiss_id] is not None:
                    db_id = self.id_map[faiss_id]
                    results.append({
                        'db_id': db_id,  # 数据库中的ID
                        'score': float(score)  # 相似度分数
                    })

            return results

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    def remove_vector_by_db_id(self, db_id: int) -> bool:
        """
        FAISS删除向量比较复杂，通常建议重建索引。
        对于这个量级，如果删除操作不频繁，可以考虑重建索引。

        当前实现：标记为删除，但物理上仍然存在
        生产环境建议定期重建索引来清理已删除的向量
        """
        try:
            # 在id_map中找到对应的位置并标记为None
            for i, mapped_id in enumerate(self.id_map):
                if mapped_id == db_id:
                    self.id_map[i] = None
                    logger.info(f"标记向量删除: db_id={db_id}, faiss_id={i}")
                    break
            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False

    def rebuild_index(self, vectors_data: List[Tuple[int, np.ndarray]]) -> bool:
        """
        重建整个索引 (用于清理已删除的向量或批量更新)

        vectors_data: [(db_id, vector), ...]
        """
        try:
            logger.info("开始重建FAISS索引...")

            # 删除旧的索引文件
            try:
                if os.path.exists(self.index_file):
                    os.remove(self.index_file)
                if os.path.exists(self.id_map_file):
                    os.remove(self.id_map_file)
            except Exception as e:
                logger.warning(f"删除旧索引文件失败: {e}")

            # 创建新索引
            self._create_new_index()

            # 重新添加所有向量
            for db_id, vector in vectors_data:
                self.add_vector(db_id, vector)

            # 立即保存新索引
            self.save()

            logger.info(f"索引重建完成，包含 {self.index.ntotal} 个向量")
            return True

        except Exception as e:
            logger.error(f"重建索引失败: {e}")
            # 尝试重新加载旧索引
            try:
                self._load_or_create_index()
            except:
                pass
            return False

    def count(self) -> int:
        """返回当前索引中的向量数量"""
        return self.index.ntotal

    def get_stats(self) -> Dict:
        """获取索引统计信息"""
        return {
            'total_vectors': self.index.ntotal,
            'dimension': self.dimension,
            'index_type': 'HNSW',
            'metric_type': 'InnerProduct (Cosine)',
            'ef_construction': getattr(self.index, 'efConstruction', 80),
            'ef_search': getattr(self.index, 'efSearch', 64),
            'memory_usage_mb': self._estimate_memory_usage()
        }

    def _estimate_memory_usage(self) -> float:
        """估算内存使用量 (MB)"""
        # HNSW索引内存估算：向量数据 + 图结构
        vector_memory = self.index.ntotal * self.dimension * 4  # float32 = 4 bytes
        graph_memory = self.index.ntotal * config.FAISS_HNSW_M * 4  # 邻居指针
        total_bytes = vector_memory + graph_memory
        return total_bytes / (1024 * 1024)

# 全局单例
_engine = None

def get_vector_engine() -> VectorEngine:
    global _engine
    if _engine is None:
        _engine = VectorEngine()
    return _engine
