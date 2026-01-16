import faiss
import numpy as np
import os
import pickle
import logging
import json
from typing import List, Dict, Tuple
try:
    from .config import config
except ImportError:
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
        """创建新的FAISS HNSW索引，优化参数设置"""
        logger.info("创建新的FAISS HNSW索引...")

        # HNSW64: 图结构，查询极快，准确率高
        # InnerProduct (IP) 在归一化向量上等同于余弦相似度
        self.index = faiss.IndexHNSWFlat(
            self.dimension,
            config.FAISS_HNSW_M,
            faiss.METRIC_INNER_PRODUCT
        )

        # 设置构建参数 (兼容不同版本的FAISS)
        ef_construction_set = False
        ef_search_set = False

        try:
            # 尝试设置HNSW参数 (新版本FAISS >= 1.7.0)
            if hasattr(self.index, 'efConstruction'):
                self.index.efConstruction = config.FAISS_EF_CONSTRUCTION  # 构建时的深度，越高越准但构建越慢
                ef_construction_set = True
                logger.info(f"设置efConstruction = {config.FAISS_EF_CONSTRUCTION}")

            if hasattr(self.index, 'efSearch'):
                self.index.efSearch = config.FAISS_EF_SEARCH  # 搜索时的深度，越高越准但搜索越慢
                ef_search_set = True
                logger.info(f"设置efSearch = {config.FAISS_EF_SEARCH}")

        except AttributeError:
            logger.warning("FAISS版本不支持efConstruction/efSearch参数，将使用默认值")

        # 如果无法设置参数，提供性能优化建议
        if not ef_construction_set or not ef_search_set:
            logger.info("💡 FAISS性能优化建议:")
            logger.info(f"   - 当前FAISS版本: {faiss.__version__}")
            logger.info("   - 建议升级到FAISS >= 1.7.0以获得最佳性能")
            logger.info("   - 或者使用: pip install faiss-cpu --upgrade")

        # 设置其他兼容性参数
        try:
            # 设置HNSW的M参数 (如果支持)
            if hasattr(self.index, 'hnsw'):
                logger.info(f"HNSW M参数 = {config.FAISS_HNSW_M}")
        except:
            pass

        self.id_map = []

        # 确保目录存在
        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)

        logger.info("✅ FAISS HNSW索引创建完成")

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
        import time
        start_time = time.time()

        if self.index.ntotal == 0:
            logger.info("FAISS索引为空，跳过搜索")
            return []

        try:
            # 确保查询向量格式正确
            if isinstance(query_vector, list):
                query_vector = np.array(query_vector, dtype='float32')
            elif query_vector.dtype != np.float32:
                query_vector = query_vector.astype('float32')

            query_vector = query_vector.reshape(1, -1)

            logger.info(f"开始FAISS搜索，索引大小: {self.index.ntotal}, top_k: {top_k}")

            # 执行搜索
            # 强制使用单线程进行搜索，防止在 Flask/MacOS 环境下发生 OpenMP 死锁
            faiss.omp_set_num_threads(1)
            search_start = time.time()
            distances, indices = self.index.search(query_vector, top_k)
            search_time = time.time() - search_start
            logger.info(f"FAISS搜索完成，耗时: {search_time:.3f}秒")

            results = []
            for i in range(min(top_k, len(indices[0]))):
                faiss_id = indices[0][i]
                score = distances[0][i]

                if faiss_id != -1 and faiss_id < len(self.id_map) and self.id_map[faiss_id] is not None:
                    db_id = self.id_map[faiss_id]
                    results.append({
                        'db_id': db_id,
                        'score': float(score)
                    })

            total_time = time.time() - start_time
            logger.info(f"搜索总耗时: {total_time:.3f}秒, 返回{len(results)}个结果")
            return results

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    def remove_vector_by_db_id(self, db_id: int) -> bool:
        """
        从FAISS索引中删除向量。由于FAISS不支持直接删除单个向量，
        我们标记删除并定期重建索引（性能优化版本）。
        """
        try:
            # 标记要删除的向量
            vector_removed = False
            for i, mapped_id in enumerate(self.id_map):
                if mapped_id == db_id:
                    self.id_map[i] = None
                    vector_removed = True
                    logger.info(f"标记向量删除: db_id={db_id}, faiss_id={i}")
                    break

            # 性能优化：不立即重建索引，只保存状态
            # 只有当删除的向量比例超过阈值时才重建
            if vector_removed:
                deleted_count = sum(1 for id_val in self.id_map if id_val is None)
                total_count = len(self.id_map)
                deletion_ratio = deleted_count / total_count if total_count > 0 else 0

                # 如果删除比例超过30%，则重建索引清理碎片
                if deletion_ratio > 0.3:
                    logger.info(f"删除比例({deletion_ratio:.1%})过高，重建索引清理碎片")
                    self._rebuild_index_after_removal()
                else:
                    # 只保存索引状态，不重建
                    self.save()

            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False

    def _rebuild_index_after_removal(self):
        """删除向量后重建索引（优化版：直接使用数据库中已存的 features，不重新跑模型）"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            valid_vectors = []

            # 只保留那些仍然“未被标记删除”的 db_id
            alive_db_ids = {mapped_id for mapped_id in self.id_map if mapped_id is not None}

            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, features FROM product_images WHERE id IS NOT NULL AND features IS NOT NULL")
                for row in cursor.fetchall():
                    img_id = row['id']
                    if img_id not in alive_db_ids:
                        continue

                    features_str = row['features']
                    try:
                        vec = np.array(json.loads(features_str), dtype='float32')
                        if vec.shape[0] != self.dimension:
                            continue
                        valid_vectors.append((img_id, vec))
                    except Exception:
                        continue

            # 重建索引
            self._create_new_index()
            for img_id, vec in valid_vectors:
                self.add_vector(img_id, vec)

            self.save()
            logger.info(f"索引重建完成，包含 {len(valid_vectors)} 个向量")

        except Exception as e:
            logger.error(f"重建索引失败: {e}")

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
        ef_construction = getattr(self.index, 'efConstruction', '不支持')
        ef_search = getattr(self.index, 'efSearch', '不支持')

        return {
            'total_vectors': self.index.ntotal,
            'dimension': self.dimension,
            'index_type': 'HNSW',
            'metric_type': 'InnerProduct (Cosine)',
            'ef_construction': ef_construction,
            'ef_search': ef_search,
            'memory_usage_mb': self._estimate_memory_usage(),
            'faiss_version': faiss.__version__,
            'performance_tips': self._get_performance_tips()
        }

    def _get_performance_tips(self) -> List[str]:
        """获取性能优化建议"""
        tips = []

        # 检查FAISS版本
        try:
            version_parts = faiss.__version__.split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1])

            if major < 1 or (major == 1 and minor < 7):
                tips.append("建议升级FAISS到1.7.0+版本以获得efConstruction/efSearch参数支持")
        except:
            tips.append("无法检测FAISS版本，建议升级到最新版本")

        # 检查ef参数
        if not hasattr(self.index, 'efConstruction'):
            tips.append("当前FAISS版本不支持efConstruction参数，搜索性能可能受限")

        if not hasattr(self.index, 'efSearch'):
            tips.append("当前FAISS版本不支持efSearch参数，建议手动设置搜索参数")

        # 检查向量数量
        if self.index.ntotal < 1000:
            tips.append("向量数量较少，考虑增加更多商品数据以提高搜索准确性")

        # 检查内存使用
        memory_mb = self._estimate_memory_usage()
        if memory_mb > 1000:  # 超过1GB
            tips.append(f"内存使用量较大 ({memory_mb:.1f}MB)，建议监控内存使用情况")

        return tips if tips else ["系统运行正常，无性能优化建议"]

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
