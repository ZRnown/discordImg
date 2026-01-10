import sqlite3
import numpy as np
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from pymilvus import MilvusClient
from config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # SQLite 数据库路径 (用于存储商品元数据和Discord账号信息)
        self.db_path = os.path.join(os.path.dirname(__file__), 'data', 'metadata.db')

        # Milvus Lite 数据库路径 (用于存储向量数据)
        self.milvus_db_path = os.path.join(os.path.dirname(__file__), 'data', 'milvus.db')

        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化 SQLite 数据库
        self.init_sqlite_database()

        # 延迟初始化 Milvus Lite 客户端 (在需要时才初始化)
        self.milvus_client = None
        self._milvus_initialized = False

    def init_sqlite_database(self):
        """初始化 SQLite 数据库 (用于元数据存储)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 创建商品表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    description TEXT,
                    english_title TEXT,
                    cnfans_url TEXT,
                    ruleEnabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 为现有表添加新字段（如果不存在）
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN ruleEnabled BOOLEAN DEFAULT 1')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            # 新增英文标题与 cnfans 链接字段（兼容已有数据库）
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN english_title TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN cnfans_url TEXT')
            except sqlite3.OperationalError:
                pass

            # 创建图片表 (milvus_id 替代 faiss_id)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    image_index INTEGER NOT NULL,
                    milvus_id INTEGER UNIQUE,
                    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
                    UNIQUE(product_id, image_index)
                )
            ''')

            # 创建 Discord 账号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS discord_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    token TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'offline',
                    last_active TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建账号轮换配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_rotation_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled BOOLEAN DEFAULT 0,
                    rotation_interval INTEGER DEFAULT 10,
                    current_account_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认轮换配置
            cursor.execute('''
                INSERT OR IGNORE INTO account_rotation_config (id, enabled, rotation_interval)
                VALUES (1, 0, 10)
            ''')

            # 创建搜索历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_image_path TEXT NOT NULL,
                    matched_product_id INTEGER,
                    matched_image_index INTEGER,
                    similarity REAL NOT NULL,
                    threshold REAL NOT NULL,
                    search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matched_product_id) REFERENCES products (id) ON DELETE SET NULL
                )
            ''')

            conn.commit()

    def init_milvus_client(self):
        """初始化 Milvus Lite 客户端"""
        try:
            # 使用 Milvus Lite 本地文件存储
            self.milvus_client = MilvusClient(uri=self.milvus_db_path)
            logger.info(f"✅ Milvus Lite 客户端初始化成功: {self.milvus_db_path}")

            # 创建 image_embeddings collection (如果不存在)
            self._create_collection_if_not_exists()

        except Exception as e:
            logger.error(f"❌ Milvus Lite 客户端初始化失败: {e}")
            raise e

    def _ensure_milvus_initialized(self):
        """确保 Milvus 客户端已初始化"""
        if not self._milvus_initialized:
            try:
                self.init_milvus_client()
                self._milvus_initialized = True
            except Exception as e:
                logger.error(f"初始化 Milvus 客户端失败: {e}")
                raise e

    def _create_collection_if_not_exists(self):
        """创建向量集合 (如果不存在)"""
        collection_name = "image_embeddings"

        try:
            # 检查集合是否存在
            if self.milvus_client.has_collection(collection_name=collection_name):
                logger.info(f"集合 {collection_name} 已存在")
                return

            # 创建新集合
            self.milvus_client.create_collection(
                collection_name=collection_name,
                vector_field_name="vector",
                dimension=512,  # PP-ShiTuV2 输出512维向量
                auto_id=True,   # 自动生成ID
                enable_dynamic_field=True,
                metric_type="COSINE"  # 余弦相似度
            )

            logger.info(f"✅ 创建 Milvus 集合: {collection_name} (512维, COSINE)")

        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            raise e

    @contextmanager
    def get_connection(self):
        """获取 SQLite 数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # 启用行工厂
            yield conn
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def execute_query(self, query: str, params: tuple = None, fetch: bool = True) -> List[Dict]:
        """执行查询并返回结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            if fetch:
                results = [dict(row) for row in cursor.fetchall()]
                conn.commit()
                return results
            conn.commit()
            return []

    def insert_product(self, product_data: Dict) -> int:
        """插入商品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO products
                (product_url, title, description, english_title, cnfans_url, ruleEnabled)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                product_data['product_url'],
                product_data.get('title', ''),
                product_data.get('description', ''),
                product_data.get('english_title', ''),
                product_data.get('cnfans_url', ''),
                product_data.get('ruleEnabled', True)
            ))
            product_id = cursor.lastrowid
            conn.commit()
            return product_id

    def insert_image_vector(self, product_id: int, image_path: str,
                           image_index: int, vector: List[float]) -> bool:
        """插入图像向量到 Milvus"""
        try:
            # 确保 Milvus 已初始化
            self._ensure_milvus_initialized()

            # 获取商品URL
            product_url = self._get_product_url_by_id(product_id) or ""

            # 准备插入数据 (一次性插入所有字段)
            data = {
                "vector": vector,  # 512维向量
                "product_id": product_id,
                "image_path": image_path,
                "image_index": image_index,
                "product_url": product_url
            }

            # 插入到 Milvus
            result = self.milvus_client.insert(
                collection_name="image_embeddings",
                data=[data]
            )

            logger.info(f"Milvus insert result: {result}")

            # 处理不同的返回值格式
            if isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict) and 'id' in result[0]:
                    milvus_id = result[0]['id']
                else:
                    milvus_id = result[0]  # 可能是直接的ID
            elif hasattr(result, 'primary_keys') and result.primary_keys:
                milvus_id = result.primary_keys[0]
            elif isinstance(result, dict) and 'ids' in result:
                milvus_id = result['ids'][0] if result['ids'] else None
            else:
                # 如果无法解析，尝试使用 upsert 方法重新插入完整数据
                try:
                    upsert_result = self.milvus_client.upsert(
                        collection_name="image_embeddings",
                        data=[data]
                    )
                    logger.info(f"使用 upsert 重新插入: {upsert_result}")
                    milvus_id = 1  # 假设成功，暂时使用占位符
                except Exception as upsert_e:
                    logger.error(f"Upsert 也失败: {upsert_e}")
                    milvus_id = None

            if milvus_id is None:
                logger.error(f"Milvus 插入失败: 无法解析返回值 {result}")
                return False

            logger.info(f"成功解析 milvus_id: {milvus_id}")

            # 保存到 SQLite 数据库
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO product_images
                    (product_id, image_path, image_index, milvus_id)
                    VALUES (?, ?, ?, ?)
                ''', (product_id, image_path, image_index, milvus_id))
                conn.commit()

            logger.info(f"向量插入成功: product_id={product_id}, image_index={image_index}, milvus_id={milvus_id}")
            return True

        except Exception as e:
            logger.error(f"插入图像向量失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def search_similar_images(self, query_vector: List[float], limit: int = 1,
                             threshold: float = 0.75) -> List[Dict]:
        """使用 Milvus 搜索相似图像"""
        try:
            # 确保 Milvus 已初始化
            self._ensure_milvus_initialized()

            # 搜索参数
            search_params = {
                "metric_type": "COSINE",
                "params": {}
            }

            # 执行搜索
            results = self.milvus_client.search(
                collection_name="image_embeddings",
                data=[query_vector],
                output_fields=["product_id", "image_path", "image_index", "product_url"],
                search_params=search_params,
                limit=limit  # 只取最相似的一个
            )

            matched_results = []

            if results and len(results) > 0:
                for hit in results[0]:
                    score = hit['distance']  # COSINE 距离分数

                    # 只有当相似度分数大于阈值时才返回结果
                    if score >= threshold:
                        entity = hit['entity']

                        # 从 SQLite 获取完整的产品信息
                        product_info = self._get_product_info_by_id(entity['product_id'])

                        if product_info:
                            result = {
                                **product_info,
                                'similarity': score,
                                'image_index': entity['image_index'],
                                'image_path': entity['image_path']
                            }
                            matched_results.append(result)
                            break  # 只返回最相似的一个结果

            return matched_results

        except Exception as e:
            logger.error(f"Milvus 搜索失败: {e}")
            return []

    def _get_product_url_by_id(self, product_id: int) -> Optional[str]:
        """根据产品ID获取产品URL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT product_url FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return row['product_url'] if row else None

    def _get_product_info_by_id(self, product_id: int) -> Optional[Dict]:
        """根据产品ID获取完整的产品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_indexed_product_ids(self) -> List[str]:
        """获取已建立索引的商品URL列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT p.product_url
                FROM products p
                JOIN product_images pi ON p.id = pi.product_id
            ''')
            return [row['product_url'] for row in cursor.fetchall()]

    def delete_product_images(self, product_id: int) -> bool:
        """删除商品的所有图像"""
        try:
            # 从 Milvus 中删除向量 (需要根据条件删除)
            # 注意: Milvus Lite 的删除功能可能有限制，这里简化处理
            filter_expr = f"product_id == {product_id}"
            try:
                self.milvus_client.delete(
                    collection_name="image_embeddings",
                    filter=filter_expr
                )
                logger.info(f"从 Milvus 删除 product_id={product_id} 的向量")
            except Exception as e:
                logger.warning(f"Milvus 删除失败 (可能不支持): {e}")

            # 从 SQLite 删除
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                conn.commit()

            return True
        except Exception as e:
            logger.error(f"删除商品图像失败: {e}")
            return False

    def delete_image_vector(self, product_id: int, image_index: int) -> bool:
        """删除特定的图像向量"""
        try:
            # 从 Milvus 中删除特定向量
            filter_expr = f"product_id == {product_id} && image_index == {image_index}"
            try:
                self.milvus_client.delete(
                    collection_name="image_embeddings",
                    filter=filter_expr
                )
                logger.info(f"从 Milvus 删除 product_id={product_id}, image_index={image_index} 的向量")
            except Exception as e:
                logger.warning(f"Milvus 删除失败 (可能不支持): {e}")

            # 从 SQLite 删除
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ? AND image_index = ?",
                             (product_id, image_index))
                conn.commit()

            return True
        except Exception as e:
            logger.error(f"删除图像向量失败: {e}")
            return False

    def get_product_by_url(self, product_url: str) -> Optional[Dict]:
        """根据商品URL获取商品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE product_url = ?", (product_url,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_product_id_by_url(self, product_url: str) -> Optional[int]:
        """根据商品URL获取商品内部ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM products WHERE product_url = ?", (product_url,))
            row = cursor.fetchone()
            return row['id'] if row else None

    def get_total_indexed_images(self) -> int:
        """获取已索引的总图片数量"""
        try:
            # 确保 Milvus 已初始化
            self._ensure_milvus_initialized()

            # 使用 num_entities 获取集合中的实体数量
            stats = self.milvus_client.query(
                collection_name="image_embeddings",
                output_fields=["count(*)"]
            )
            return len(stats) if stats else 0
        except Exception as e:
            logger.error(f"获取索引图片数量失败: {e}")
            return 0

    def get_indexed_product_urls(self) -> List[str]:
        """获取已建立索引的商品URL列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT p.product_url
                    FROM products p
                    JOIN product_images pi ON p.id = pi.product_id
                    WHERE pi.milvus_id IS NOT NULL
                ''')
                return [row['product_url'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取已索引商品URL失败: {e}")
            return []

    def add_search_history(self, query_image_path: str, matched_product_id: int,
                          matched_image_index: int, similarity: float, threshold: float) -> bool:
        """添加搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO search_history
                    (query_image_path, matched_product_id, matched_image_index, similarity, threshold)
                    VALUES (?, ?, ?, ?, ?)
                ''', (query_image_path, matched_product_id, matched_image_index, similarity, threshold))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加搜索历史失败: {e}")
            return False

    def get_search_history(self, limit: int = 50) -> List[Dict]:
        """获取搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        sh.id,
                        sh.query_image_path,
                        sh.matched_product_id,
                        sh.matched_image_index,
                        sh.similarity,
                        sh.threshold,
                        sh.search_time,
                        p.title,
                        p.english_title,
                        p.product_url as weidian_url,
                        p.cnfans_url,
                        p.ruleEnabled,
                        pi.image_path as matched_image_path
                    FROM search_history sh
                    LEFT JOIN products p ON sh.matched_product_id = p.id
                    LEFT JOIN product_images pi ON sh.matched_product_id = pi.product_id AND sh.matched_image_index = pi.image_index
                    ORDER BY sh.search_time DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                history = []
                for row in rows:
                    history.append({
                        'id': row['id'],
                        'query_image_path': row['query_image_path'],
                        'matched_product_id': row['matched_product_id'],
                        'matched_image_index': row['matched_image_index'],
                        'similarity': row['similarity'],
                        'threshold': row['threshold'],
                        'search_time': row['search_time'],
                        'title': row['title'],
                        'english_title': row['english_title'],
                        'weidian_url': row['weidian_url'],
                        'cnfans_url': row['cnfans_url'],
                        'ruleEnabled': row['ruleEnabled'],
                        'matched_image_path': row['matched_image_path']
                    })
                return history
        except Exception as e:
            logger.error(f"获取搜索历史失败: {e}")
            return []

    def delete_search_history(self, history_id: int) -> bool:
        """删除搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM search_history WHERE id = ?', (history_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除搜索历史失败: {e}")
            return False

    def clear_search_history(self) -> bool:
        """清空所有搜索历史"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM search_history')
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"清空搜索历史失败: {e}")
            return False

# 全局数据库实例
db = Database()
