#!/usr/bin/env python3
"""
数据库清理脚本
清空所有数据库数据、图片文件和向量索引

使用方法:
cd backend
python3 clear_database.py

或者直接运行:
python3 clear_database.py --confirm
"""

import os
import sys
import sqlite3
import shutil
from pathlib import Path

def clear_all_data(confirm=False):
    """清空所有数据"""
    if not confirm:
        print("⚠️ 警告: 此操作将清空所有数据！")
        print("包括: 用户账户、商品数据、图片文件、向量索引等")
        print("")
        response = input("确认要清空所有数据吗？输入 'YES' 确认: ")
        if response != 'YES':
            print("操作已取消")
            return

    # 数据目录
    DATA_DIR = Path('data')

    # 所有数据库文件
    DB_FILES = [
        'data/app.db',
        'data/metadata.db',
        'data/milvus.db',
        'data/discord_bot.db'  # 万一存在
    ]

    print('🗑️ 开始全面清空所有数据库和相关数据...')

    # 1. 清空所有SQLite数据库
    for db_path in DB_FILES:
        if os.path.exists(db_path):
            print(f'📄 清空SQLite数据库: {db_path}')
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                # 获取所有表名
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                # 清空所有表
                for table in tables:
                    table_name = table[0]
                    if table_name != 'sqlite_sequence':  # 跳过SQLite内部表
                        print(f'  删除表 {table_name} 的所有数据')
                        cursor.execute(f'DELETE FROM {table_name}')

                        # 重置自增ID
                        cursor.execute(f'DELETE FROM sqlite_sequence WHERE name="{table_name}"')

                conn.commit()
                conn.close()
                print(f'✅ {db_path} 已清空')

            except Exception as e:
                print(f'❌ 清空 {db_path} 失败: {e}')
        else:
            print(f'⚠️ 数据库文件不存在: {db_path}')

    # 2. 删除图片文件
    IMAGES_DIR = DATA_DIR / 'scraped_images'
    if IMAGES_DIR.exists():
        print(f'🖼️ 删除图片目录: {IMAGES_DIR}')
        try:
            shutil.rmtree(IMAGES_DIR)
            print('✅ 图片目录已删除')
        except Exception as e:
            print(f'❌ 删除图片目录失败: {e}')
    else:
        print('⚠️ 图片目录不存在')

    # 3. 删除向量数据目录
    VECTOR_DIR = DATA_DIR / 'vectors'
    if VECTOR_DIR.exists():
        print(f'🔍 删除向量数据目录: {VECTOR_DIR}')
        try:
            shutil.rmtree(VECTOR_DIR)
            print('✅ 向量数据目录已删除')
        except Exception as e:
            print(f'❌ 删除向量数据目录失败: {e}')
    else:
        print('⚠️ 向量数据目录不存在')

    # 4. 删除向量索引文件
    vector_extensions = ['*.faiss', '*.index', '*.pkl', '*.npy', '*.bin']
    vector_files = []
    for ext in vector_extensions:
        vector_files.extend(list(DATA_DIR.glob(ext)))

    if vector_files:
        print('🔍 删除向量索引文件:')
        for vf in vector_files:
            try:
                vf.unlink()
                print(f'  ✅ 删除: {vf}')
            except Exception as e:
                print(f'  ❌ 删除失败 {vf}: {e}')

    # 5. 删除临时文件
    temp_files = list(DATA_DIR.glob('temp_*')) + list(DATA_DIR.glob('*.tmp'))
    if temp_files:
        print('🗂️ 删除临时文件:')
        for tf in temp_files:
            try:
                tf.unlink()
                print(f'  ✅ 删除: {tf}')
            except Exception as e:
                print(f'  ❌ 删除失败 {tf}: {e}')

    print('\n🎉 全面数据库清理完成！')
    print('\n📋 清理内容总结:')
    print('  - 所有SQLite数据库 (app.db, metadata.db, milvus.db) 已清空')
    print('  - 自增ID计数器已重置')
    print('  - 图片文件目录已删除')
    print('  - 向量数据目录已删除')
    print('  - 向量索引文件 (*.faiss, *.index, *.pkl, *.npy, *.bin) 已删除')
    print('  - 临时文件已删除')
    print('\n⚠️ 注意: 所有用户账户、商品数据、系统配置、向量索引都已被清空')
    print('   这是一个不可逆的操作，如需恢复请从备份恢复')

if __name__ == '__main__':
    confirm = '--confirm' in sys.argv
    clear_all_data(confirm)
