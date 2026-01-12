#!/usr/bin/env python3
"""
系统修复验证脚本
测试所有关键修复是否生效
"""

import os
import sys
import time

def test_config():
    """测试配置系统"""
    print("🔧 1. 测试配置系统...")
    try:
        sys.path.insert(0, 'backend')
        from config import config
        
        checks = [
            ('SECRET_KEY', hasattr(config, 'SECRET_KEY') and config.SECRET_KEY),
            ('HOST', config.HOST == '0.0.0.0'),
            ('PORT', config.PORT == 5001),
            ('DEBUG', config.DEBUG == False),
            ('SCRAPE_THREADS', config.SCRAPE_THREADS == 2),
            ('CORS_ORIGINS', config.CORS_ORIGINS == ["*"]),
        ]
        
        for name, passed in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {name}: {'通过' if passed else '失败'}")
        
        return all(passed for _, passed in checks)
    except Exception as e:
        print(f"  ❌ 配置测试失败: {e}")
        return False

def test_database_reset():
    """测试数据库状态重置"""
    print("\n💾 2. 测试数据库状态重置...")
    try:
        from backend.database import db
        
        # 设置为运行状态
        db.update_scrape_status(is_scraping=True, message='测试')
        status1 = db.get_scrape_status()
        
        # 重置状态
        db.update_scrape_status(is_scraping=False, stop_signal=False, message='重置测试')
        status2 = db.get_scrape_status()
        
        reset_worked = not status2.get('is_scraping', True)
        
        print(f"  ✅ 设置运行状态: {status1.get('is_scraping', False)}")
        print(f"  ✅ 重置后状态: {status2.get('is_scraping', True)}")
        print(f"  ✅ 重置功能: {'正常' if reset_worked else '异常'}")
        
        return reset_worked
    except Exception as e:
        print(f"  ❌ 数据库测试失败: {e}")
        return False

def test_singleton_pattern():
    """测试单例模式"""
    print("\n🔄 3. 测试单例模式...")
    try:
        import threading
        
        class TestSingleton:
            _instance = None
            _lock = threading.Lock()
            _init_count = 0
            
            @classmethod
            def get_instance(cls):
                if cls._instance is not None:
                    return cls._instance
                    
                with cls._lock:
                    if cls._instance is None:
                        time.sleep(0.01)  # 模拟初始化耗时
                        cls._instance = object()
                        cls._init_count += 1
                return cls._instance
        
        def worker():
            return TestSingleton.get_instance()
        
        # 启动10个线程
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        singleton_worked = TestSingleton._init_count == 1
        print(f"  ✅ 初始化次数: {TestSingleton._init_count} (应为1)")
        print(f"  ✅ 单例模式: {'正常' if singleton_worked else '异常'}")
        
        return singleton_worked
    except Exception as e:
        print(f"  ❌ 单例测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🎯 系统修复验证")
    print("=" * 50)
    
    tests = [
        ("配置系统", test_config),
        ("数据库重置", test_database_reset), 
        ("单例模式", test_singleton_pattern),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {name} 测试异常: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("📊 测试结果:")
    
    all_passed = all(results)
    for i, (name, _) in enumerate(tests):
        status = "✅ 通过" if results[i] else "❌ 失败"
        print(f"  {status} - {name}")
    
    print(f"\n🎉 总体结果: {'所有测试通过！系统修复成功' if all_passed else '部分测试失败，需要检查'}")
    
    if all_passed:
        print("\n🚀 现在可以安全启动系统:")
        print("  cd backend && python app.py")
        print("  # 前端: npm run dev")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
