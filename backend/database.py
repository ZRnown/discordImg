import sqlite3
import numpy as np
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # SQLite 数据库路径 (用于存储商品元数据和Discord账号信息)
        self.db_path = os.path.join(os.path.dirname(__file__), 'data', 'metadata.db')

        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化 SQLite 数据库
        self.init_sqlite_database()

    def init_sqlite_database(self):
        """初始化 SQLite 数据库 (用于元数据存储)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 创建商品表（移除商品级别延迟，使用全局延迟）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    description TEXT,
                    english_title TEXT,
                    cnfans_url TEXT,
                    acbuy_url TEXT,
                    shop_name TEXT,
                    ruleEnabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建店铺表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    product_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 为现有表添加新字段（如果不存在）
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN ruleEnabled BOOLEAN DEFAULT 1')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN min_delay INTEGER DEFAULT 3')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN max_delay INTEGER DEFAULT 8')
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

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN acbuy_url TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN shop_name TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN cnfans_channel_id TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN acbuy_channel_id TEXT')
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

            # 创建全局延迟配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_reply_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    min_delay REAL DEFAULT 3.0,
                    max_delay REAL DEFAULT 8.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认全局延迟配置
            cursor.execute('''
                INSERT OR IGNORE INTO global_reply_config (id, min_delay, max_delay)
                VALUES (1, 3.0, 8.0)
            ''')

            conn.commit()


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
                (product_url, title, description, english_title, cnfans_url, acbuy_url, shop_name, ruleEnabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                product_data['product_url'],
                product_data.get('title', ''),
                product_data.get('description', ''),
                product_data.get('english_title', ''),
                product_data.get('cnfans_url', ''),
                product_data.get('acbuy_url', ''),
                product_data.get('shop_name', ''),
                product_data.get('ruleEnabled', True)
            ))
            product_id = cursor.lastrowid
            conn.commit()
            return product_id

    def insert_image_record(self, product_id: int, image_path: str, image_index: int) -> int:
        """插入图像记录到数据库，返回记录ID供FAISS使用"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO product_images
                    (product_id, image_path, image_index)
                    VALUES (?, ?, ?)
                ''', (product_id, image_path, image_index))
                conn.commit()
                record_id = cursor.lastrowid
                logger.info(f"图像记录插入成功: product_id={product_id}, image_index={image_index}, record_id={record_id}")
                return record_id

        except Exception as e:
            logger.error(f"插入图像记录失败: {e}")
            raise e

    def search_similar_images(self, query_vector: np.ndarray, limit: int = 1,
                             threshold: float = 0.6) -> List[Dict]:
        """使用FAISS搜索相似图像"""
        try:
            from vector_engine import get_vector_engine
            engine = get_vector_engine()

            print(f"DEBUG DB: Starting FAISS search, threshold: {threshold}, limit: {limit}")
            print(f"DEBUG DB: Query vector length: {len(query_vector) if hasattr(query_vector, '__len__') else 'unknown'}")

            # 执行FAISS搜索 - 请求更多结果以应对被删除的向量
            faiss_results = engine.search(query_vector, top_k=min(limit * 3, 50))  # 请求更多候选结果
            print(f"DEBUG DB: FAISS search returned {len(faiss_results)} results")

            matched_results = []

            for result in faiss_results:
                score = result['score']
                db_id = result['db_id']

                print(f"DEBUG DB: Processing result - db_id: {db_id}, score: {score}, threshold: {threshold}")

                # 通过image_db_id获取产品信息
                image_info = self.get_image_info_by_id(db_id)
                if image_info:
                    product_info = self._get_product_info_by_id(image_info['product_id'])

                    if product_info:
                        result_dict = {
                            **product_info,
                            'similarity': score,
                            'image_index': image_info['image_index'],
                            'image_path': image_info['image_path']
                        }
                        matched_results.append(result_dict)
                        print(f"DEBUG DB: Added result with similarity {score}")

                        # 如果找到了足够的结果，就停止
                        if len(matched_results) >= limit:
                            break
                    else:
                        print(f"DEBUG DB: Product info not found for product_id {image_info['product_id']}")
                else:
                    print(f"DEBUG DB: Image info not found for db_id {db_id}")

            # 如果没有找到任何结果，返回最佳匹配（即使低于阈值）
            if not matched_results and faiss_results:
                print(f"DEBUG DB: No results above threshold {threshold}, returning best match")
                best_result = faiss_results[0]
                db_id = best_result['db_id']
                image_info = self.get_image_info_by_id(db_id)
                if image_info:
                    product_info = self._get_product_info_by_id(image_info['product_id'])
                    if product_info:
                        result_dict = {
                            **product_info,
                            'similarity': best_result['score'],
                            'image_index': image_info['image_index'],
                            'image_path': image_info['image_path']
                        }
                        matched_results.append(result_dict)
                        print(f"DEBUG DB: Added best match with similarity {best_result['score']}")

            return matched_results

        except Exception as e:
            logger.error(f"FAISS搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _get_product_url_by_id(self, product_id: int) -> Optional[str]:
        """根据产品ID获取产品URL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT product_url FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return row['product_url'] if row else None

    def get_image_info_by_id(self, image_id: int) -> Optional[Dict]:
        """根据图像记录ID获取图像信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM product_images WHERE id = ?", (image_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

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
            # 从FAISS中删除向量
            from vector_engine import get_vector_engine
            engine = get_vector_engine()

            # 获取该商品的所有图像记录ID
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM product_images WHERE product_id = ?", (product_id,))
                image_ids = [row['id'] for row in cursor.fetchall()]

            # 从FAISS中删除这些向量
            for image_id in image_ids:
                engine.remove_vector_by_db_id(image_id)

            # 从 SQLite 删除
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                conn.commit()

            # 保存FAISS索引
            engine.save()

            return True
        except Exception as e:
            logger.error(f"删除商品图像失败: {e}")
            return False

    def delete_image_vector(self, product_id: int, image_index: int) -> bool:
        """删除特定的图像向量"""
        try:
            # 从FAISS中删除向量
            from vector_engine import get_vector_engine
            engine = get_vector_engine()

            # 获取该图像的记录ID
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM product_images WHERE product_id = ? AND image_index = ?",
                             (product_id, image_index))
                row = cursor.fetchone()
                if row:
                    image_id = row['id']
                    engine.remove_vector_by_db_id(image_id)

            # 从 SQLite 删除
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ? AND image_index = ?",
                             (product_id, image_index))
                conn.commit()

            # 保存FAISS索引
            engine.save()

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
            from vector_engine import get_vector_engine
            engine = get_vector_engine()
            return engine.count()
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

    def get_search_history(self, limit: int = 50, offset: int = 0) -> Dict:
        """获取搜索历史记录（支持分页）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 获取总数
                cursor.execute('SELECT COUNT(*) FROM search_history')
                total = cursor.fetchone()[0]

                # 获取分页数据
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
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
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

                return {
                    'history': history,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                    'has_more': offset + limit < total
                }
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

    def get_global_reply_config(self) -> Dict[str, float]:
        """获取全局回复延迟配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT min_delay, max_delay FROM global_reply_config WHERE id = 1')
                row = cursor.fetchone()
                if row:
                    return {'min_delay': row[0], 'max_delay': row[1]}
                return {'min_delay': 3.0, 'max_delay': 8.0}  # 默认值
        except Exception as e:
            logger.error(f"获取全局回复配置失败: {e}")
            return {'min_delay': 3.0, 'max_delay': 8.0}

    def update_global_reply_config(self, min_delay: float, max_delay: float) -> bool:
        """更新全局回复延迟配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE global_reply_config
                    SET min_delay = ?, max_delay = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''', (min_delay, max_delay))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新全局回复配置失败: {e}")
            return False

    def get_system_config(self) -> Dict[str, any]:
        """获取系统配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id FROM system_config WHERE id = 1')
                row = cursor.fetchone()
                if row:
                    return {
                        'discord_channel_id': row[0] or '',
                        'download_threads': row[1] or 4,
                        'feature_extract_threads': row[2] or 4,
                        'discord_similarity_threshold': row[3] or 0.6,
                        'cnfans_channel_id': row[4] or '',
                        'acbuy_channel_id': row[5] or ''
                    }
                # 如果没有配置记录，创建默认配置
                cursor.execute('''
                    INSERT OR IGNORE INTO system_config (id, discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id)
                    VALUES (1, '', 4, 4, 0.6, '', '')
                ''')
                conn.commit()
                return {
                    'discord_channel_id': '',
                    'download_threads': 4,
                    'feature_extract_threads': 4,
                    'discord_similarity_threshold': 0.6
                }
        except Exception as e:
            logger.error(f"获取系统配置失败: {e}")
            return {
                'discord_channel_id': '',
                'download_threads': 4,
                'feature_extract_threads': 4,
                'discord_similarity_threshold': 0.6
            }

    def update_system_config(self, discord_channel_id: str = None, download_threads: int = None,
                           feature_extract_threads: int = None, discord_similarity_threshold: float = None,
                           cnfans_channel_id: str = None, acbuy_channel_id: str = None) -> bool:
        """更新系统配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 首先确保配置记录存在
                cursor.execute('''
                    INSERT OR IGNORE INTO system_config (id, discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id)
                    VALUES (1, '', 4, 4, 0.6, '', '')
                ''')

                # 构建更新语句
                update_fields = []
                params = []

                if discord_channel_id is not None:
                    update_fields.append('discord_channel_id = ?')
                    params.append(discord_channel_id)

                if download_threads is not None:
                    update_fields.append('download_threads = ?')
                    params.append(download_threads)

                if feature_extract_threads is not None:
                    update_fields.append('feature_extract_threads = ?')
                    params.append(feature_extract_threads)

                if discord_similarity_threshold is not None:
                    update_fields.append('discord_similarity_threshold = ?')
                    params.append(discord_similarity_threshold)

                if cnfans_channel_id is not None:
                    update_fields.append('cnfans_channel_id = ?')
                    params.append(cnfans_channel_id)

                if acbuy_channel_id is not None:
                    update_fields.append('acbuy_channel_id = ?')
                    params.append(acbuy_channel_id)

                if update_fields:
                    update_fields.append('updated_at = CURRENT_TIMESTAMP')
                    sql = f'UPDATE system_config SET {", ".join(update_fields)} WHERE id = 1'
                    cursor.execute(sql, params)
                    conn.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"更新系统配置失败: {e}")
            return False

    # ===== 店铺管理方法 =====

    def add_shop(self, shop_id: str, name: str) -> bool:
        """添加新店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 检查店铺是否已存在
                cursor.execute('SELECT id FROM shops WHERE shop_id = ?', (shop_id,))
                if cursor.fetchone():
                    logger.warning(f"店铺 {shop_id} 已存在")
                    return False

                cursor.execute('''
                    INSERT INTO shops (shop_id, name, product_count)
                    VALUES (?, ?, 0)
                ''', (shop_id, name))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加店铺失败: {e}")
            return False

    def get_all_shops(self) -> List[Dict]:
        """获取所有店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM shops ORDER BY created_at DESC')
                rows = cursor.fetchall()

                shops = []
                for row in rows:
                    shops.append({
                        'id': row[0],
                        'shop_id': row[1],
                        'name': row[2],
                        'product_count': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    })
                return shops
        except Exception as e:
            logger.error(f"获取店铺列表失败: {e}")
            return []

    def get_shop_by_id(self, shop_id: str) -> Optional[Dict]:
        """根据shop_id获取店铺信息"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM shops WHERE shop_id = ?', (shop_id,))
                row = cursor.fetchone()

                if row:
                    return {
                        'id': row[0],
                        'shop_id': row[1],
                        'name': row[2],
                        'product_count': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    }
                return None
        except Exception as e:
            logger.error(f"获取店铺信息失败: {e}")
            return None

    def update_shop_product_count(self, shop_id: str, product_count: int) -> bool:
        """更新店铺的商品数量"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE shops
                    SET product_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE shop_id = ?
                ''', (product_count, shop_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新店铺商品数量失败: {e}")
            return False

    def delete_shop(self, shop_id: str) -> bool:
        """删除店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM shops WHERE shop_id = ?', (shop_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除店铺失败: {e}")
            return False

# 全局数据库实例
db = Database()
