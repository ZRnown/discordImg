#!/usr/bin/env python3
"""
403 Forbidden 错误诊断脚本

使用方法:
python diagnose_403.py

此脚本会检查常见的403 Forbidden错误原因：
1. CORS配置
2. Cookie设置
3. 防火墙规则
4. Nginx配置
"""

import os
import requests
import socket
from urllib.parse import urlparse

def check_cors_configuration():
    """检查CORS配置"""
    print("🔍 检查CORS配置...")
    try:
        from config import config
        print("✅ CORS允许的源:")
        for origin in config.CORS_ORIGINS:
            print(f"   - {origin.strip()}")
    except Exception as e:
        print(f"❌ CORS配置检查失败: {e}")

def check_network_connectivity():
    """检查网络连通性"""
    print("\n🔍 检查网络连通性...")

    # 检查本地端口
    def check_port(host, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False

    # 检查本地服务
    if check_port('127.0.0.1', 5001):
        print("✅ 本地后端服务 (127.0.0.1:5001) 正在运行")
    else:
        print("❌ 本地后端服务 (127.0.0.1:5001) 未运行")

    if check_port('127.0.0.1', 3000):
        print("✅ 本地前端服务 (127.0.0.1:3000) 正在运行")
    else:
        print("❌ 本地前端服务 (127.0.0.1:3000) 未运行")

def check_api_endpoints():
    """检查API端点可访问性"""
    print("\n🔍 检查API端点可访问性...")

    base_url = "http://127.0.0.1:5001"
    endpoints = [
        '/api/auth/me',
        '/api/logs?endpoint=recent',
        '/api/user/settings'
    ]

    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            if response.status_code == 401:
                print(f"✅ {endpoint}: {response.status_code} (需要认证，正常)")
            elif response.status_code == 200:
                print(f"✅ {endpoint}: {response.status_code} (可访问)")
            else:
                print(f"⚠️  {endpoint}: {response.status_code} ({response.reason})")
        except requests.exceptions.RequestException as e:
            print(f"❌ {endpoint}: 连接失败 - {e}")

def check_environment_variables():
    """检查环境变量配置"""
    print("\n🔍 检查环境变量配置...")

    important_vars = [
        'HOST', 'PORT', 'DEBUG',
        'CORS_ORIGINS', 'SECRET_KEY',
        'SESSION_LIFETIME'
    ]

    for var in important_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: 未设置")

def check_nginx_configuration():
    """检查Nginx配置建议"""
    print("\n🔍 Nginx配置检查建议...")

    print("如果使用Nginx反向代理，请确保配置包含:")
    print("""
    server {
        listen 80;
        server_name your-domain.com;

        # 前端静态文件
        location / {
            proxy_pass http://127.0.0.1:3000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # API代理
        location /api {
            proxy_pass http://127.0.0.1:5001;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # CORS头
            add_header Access-Control-Allow-Origin *;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
            add_header Access-Control-Allow-Headers "Origin, X-Requested-With, Content-Type, Accept, Authorization";

            # 处理预检请求
            if ($request_method = 'OPTIONS') {
                return 204;
            }
        }
    }
    """)

def main():
    """主诊断函数"""
    print("🚀 403 Forbidden 错误诊断工具")
    print("=" * 50)

    check_cors_configuration()
    check_network_connectivity()
    check_api_endpoints()
    check_environment_variables()
    check_nginx_configuration()

    print("\n📋 故障排除清单:")
    print("1. 确保后端服务正在运行: python app.py")
    print("2. 确保前端服务正在运行: npm run dev")
    print("3. 清除浏览器Cookie和缓存")
    print("4. 检查防火墙是否阻止了相关端口")
    print("5. 如果使用Nginx，确保配置正确转发API请求")
    print("6. 检查服务器安全组/防火墙规则")

if __name__ == "__main__":
    main()
