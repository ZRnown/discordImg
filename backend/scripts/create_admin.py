#!/usr/bin/env python3
"""
创建管理员账号脚本

使用方法:
cd backend
python3 create_admin.py

或者指定用户名和密码:
python3 create_admin.py --username admin --password admin123
"""

import sys
import getpass
import argparse
from database import Database
from werkzeug.security import generate_password_hash

def create_admin_user(username=None, password=None):
    """创建管理员用户"""
    db = Database()

    # 如果没有提供参数，交互式输入
    if not username:
        username = input("请输入管理员用户名: ").strip()
        if not username:
            print("❌ 用户名不能为空")
            return

    if not password:
        password = getpass.getpass("请输入管理员密码: ").strip()
        if not password:
            print("❌ 密码不能为空")
            return

        # 确认密码
        confirm_password = getpass.getpass("请再次输入密码确认: ").strip()
        if password != confirm_password:
            print("❌ 两次输入的密码不一致")
            return

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 检查用户名是否已存在
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            existing_user = cursor.fetchone()

            if existing_user:
                print(f"❌ 用户名 '{username}' 已存在")
                return

            # 创建管理员用户
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, 'admin', datetime('now'), datetime('now'))
            """, (username, hashed_password))

            user_id = cursor.lastrowid
            conn.commit()

            print("✅ 管理员账号创建成功！")
            print(f"   用户名: {username}")
            print(f"   角色: 管理员")
            print(f"   用户ID: {user_id}")
            print("\n🔐 请妥善保管账号信息")

    except Exception as e:
        print(f"❌ 创建管理员账号失败: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='创建管理员账号')
    parser.add_argument('--username', help='管理员用户名')
    parser.add_argument('--password', help='管理员密码')

    args = parser.parse_args()

    if args.username and args.password:
        create_admin_user(args.username, args.password)
    else:
        create_admin_user()
