import requests
import re
import json
import time
import logging
from urllib.parse import urlparse, parse_qs, quote
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class WeidianScraper:
    """微店商品信息爬虫 - 使用官方API"""

    def __init__(self):
        self.session = requests.Session()
        # 设置固定的请求头，模拟浏览器行为
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'application/json, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
            'Origin': 'https://weidian.com',
            'Referer': 'https://weidian.com/',
            'Sec-Ch-Ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        })

        # 设置cookie
        self.session.cookies.update({
            'wdtoken': '8ea9315c',
            '__spider__visitorid': '0dcf6a5b878847ec',
            'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
            'v-components/cpn-coupon-dialog@nologinshop': '2',
            '__spider__sessionid': 'c7da7d6e06b1f1ac'
        })

    def extract_item_id(self, url: str) -> Optional[str]:
        """从微店URL中提取商品ID"""
        try:
            parsed_url = urlparse(url)
            if 'itemID' in parsed_url.query:
                query_params = parse_qs(parsed_url.query)
                return query_params.get('itemID', [None])[0]
            else:
                # 尝试从路径中提取
                path_match = re.search(r'/item/(\d+)', parsed_url.path)
                if path_match:
                    return path_match.group(1)

                # 尝试其他格式
                id_match = re.search(r'itemID[=/](\d+)', url)
                if id_match:
                    return id_match.group(1)

            return None
        except Exception as e:
            logger.error(f"提取商品ID失败: {e}")
            return None

    def extract_item_id(self, url: str) -> Optional[str]:
        """从微店URL中提取商品ID"""
        try:
            parsed_url = urlparse(url)
            if 'itemID' in parsed_url.query:
                query_params = parse_qs(parsed_url.query)
                return query_params.get('itemID', [None])[0]
            else:
                # 尝试从路径中提取
                path_match = re.search(r'/item/(\d+)', parsed_url.path)
                if path_match:
                    return path_match.group(1)

                # 尝试其他格式
                id_match = re.search(r'itemID[=/](\d+)', url)
                if id_match:
                    return id_match.group(1)

            return None
        except Exception as e:
            logger.error(f"提取商品ID失败: {e}")
            return None

    def scrape_product_info(self, url: str) -> Optional[Dict]:
        """
        抓取微店商品信息 - 使用官方API
        返回包含标题、描述、图片等信息的字典
        """
        try:
            item_id = self.extract_item_id(url)
            if not item_id:
                logger.error(f"无法从URL提取商品ID: {url}")
                return None

            logger.info(f"开始抓取商品: {item_id}")

            # 使用官方API获取商品信息
            product_info = self._scrape_by_api(item_id, url)
            if product_info:
                logger.info(f"✅ 商品信息抓取成功: {product_info.get('title', 'Unknown')}")
                return product_info

            # 如果API失败，使用备用方法
            logger.warning("API抓取失败，使用备用方法")
            return self._fallback_scrape(url, item_id)

        except Exception as e:
            logger.error(f"商品信息抓取失败: {e}")
            return None

    def _scrape_by_api(self, item_id: str, url: str) -> Optional[Dict]:
        """使用微店官方API抓取商品信息"""
        try:
            # 获取商品标题和SKU信息
            title_info = self._get_item_title_and_sku(item_id)
            if not title_info:
                return None

            # 获取商品图片信息
            image_info = self._get_item_images(item_id)
            images = image_info if image_info else []

            # 构建商品信息
            product_info = {
                'id': item_id,
                'weidian_url': url,
            # CNFans link in requested format
            'cnfans_url': f"https://cnfans.com/product?id={item_id}&platform=WEIDIAN",
                'images': images,
                'title': title_info.get('title', f'微店商品 {item_id}'),
                'english_title': self._generate_english_title(title_info.get('title', '')),
                'description': f"微店商品ID: {item_id}"
            }

            return product_info

        except Exception as e:
            logger.error(f"API抓取失败: {e}")
            return None

    def _get_item_title_and_sku(self, item_id: str) -> Optional[Dict]:
        """获取商品标题和SKU信息"""
        try:
            # 构造API URL
            param = json.dumps({"itemId": item_id})
            encoded_param = quote(param)
            timestamp = int(time.time() * 1000)

            api_url = f"https://thor.weidian.com/detail/getItemSkuInfo/1.0?param={encoded_param}&wdtoken=8ea9315c&_={timestamp}"

            logger.debug(f"调用标题API: {api_url}")

            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            # 只记录是否成功，避免打印大体JSON
            logger.debug(f"标题API返回状态: {data.get('status', {}).get('code')}")

            if data.get('status', {}).get('code') == 0:
                result = data.get('result', {})
                title = result.get('itemTitle', '')
                if title:
                    return {'title': title, 'sku_info': result}

            return None

        except Exception as e:
            logger.error(f"获取商品标题失败: {e}")
            return None

    def _get_item_images(self, item_id: str) -> List[str]:
        """获取商品图片信息"""
        try:
            # 构造API URL
            param = json.dumps({"vItemId": item_id})
            encoded_param = quote(param)
            timestamp = int(time.time() * 1000)

            api_url = f"https://thor.weidian.com/detail/getDetailDesc/1.0?param={encoded_param}&wdtoken=8ea9315c&_={timestamp}"

            logger.debug(f"调用图片API: {api_url}")

            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            logger.debug(f"图片API返回状态: {data.get('status', {}).get('code')}")

            images = []
            if data.get('status', {}).get('code') == 0:
                item_detail = data.get('result', {}).get('item_detail', {})
                desc_content = item_detail.get('desc_content', [])

                for item in desc_content:
                    if item.get('type') == 2 and item.get('url'):
                        images.append(item['url'])

            return images

        except Exception as e:
            logger.error(f"获取商品图片失败: {e}")
            return []


    def _generate_english_title(self, chinese_title: str) -> str:
        """根据中文标题生成英文标题 - 使用免费翻译API"""
        if not chinese_title or len(chinese_title.strip()) == 0:
            return ""
        # 优先使用 Google 免费接口，失败再回退到百度，再回退到简单映射
        try:
            return self._translate_with_google(chinese_title)
        except Exception as e:
            logger.debug(f"Google 翻译失败: {e}")
        try:
            res = self._translate_with_baidu(chinese_title)
            if res:
                return res
        except Exception as e:
            logger.debug(f"百度翻译失败: {e}")
        # 最后备用：简单映射
        return self._simple_chinese_to_english(chinese_title)

    def _translate_with_baidu(self, text: str) -> str:
        """使用百度翻译API"""
        try:
            # 百度翻译免费API
            url = "https://fanyi.baidu.com/transapi"

            params = {
                'from': 'zh',
                'to': 'en',
                'query': text[:200]  # 限制长度
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            # 尝试多种可能的返回结构，避免直接抛出异常
            translated = ""
            if isinstance(data, dict):
                try:
                    translated = data.get('data', {}).get('result', [{}])[0].get('dst', '') or ''
                except Exception:
                    translated = ''
                if not translated:
                    if 'trans_result' in data:
                        try:
                            translated = data.get('trans_result', [{}])[0].get('dst', '') or ''
                        except Exception:
                            translated = ''
            if translated:
                return translated.strip()
            logger.debug("百度翻译返回空结果")
            return ""
        except Exception as e:
            logger.warning(f"百度翻译API调用异常: {e}")
            return ""

    def _translate_with_google(self, text: str) -> str:
        """使用Google Translate API的免费版本"""
        try:
            # 使用Google Translate的免费API
            url = "https://translate.googleapis.com/translate_a/single"

            params = {
                'client': 'gtx',
                'sl': 'zh-CN',
                'tl': 'en',
                'dt': 't',
                'q': text[:500]  # 限制长度
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            # Google返回的是JSON数组
            data = response.json()
            if data and len(data) > 0 and len(data[0]) > 0:
                translated = data[0][0][0]
                if translated:
                    return translated.strip()

            raise Exception("Google翻译返回空结果")

        except Exception as e:
            logger.error(f"Google翻译API调用失败: {e}")
            raise e

    def _simple_chinese_to_english(self, text: str) -> str:
        """简单的中英映射 - 最后的备用方案"""
        # 简单的商品关键词映射
        mappings = {
            '鞋': 'shoes',
            '运动鞋': 'sports shoes',
            '袜子': 'socks',
            '鞋子': 'shoes',
            '衣服': 'clothes',
            '上衣': 'top',
            '裤子': 'pants',
            '包': 'bag',
            '包包': 'bag',
            '手机': 'phone',
            '电脑': 'computer',
            '耳机': 'headphones',
            '手表': 'watch',
            '眼镜': 'glasses',
            '帽子': 'hat',
            '书': 'book',
            '玩具': 'toy',
            '游戏': 'game'
        }

        result = text
        for cn, en in mappings.items():
            result = result.replace(cn, en)

        # 如果有明显的变化，返回翻译结果，否则返回空
        if result != text:
            return result.strip()
        else:
            return ""


    def _fallback_scrape(self, url: str, item_id: str) -> Optional[Dict]:
        """备用抓取方法 - 简化版"""
        try:
            logger.info(f"使用备用方法抓取商品: {item_id}")

            # 使用简化的默认信息
            product_info = {
                'id': item_id,
                'weidian_url': url,
                'cnfans_url': f"https://cnfans.com/product/?shop_type=weidian&id={item_id}",
                'images': [],  # 没有图片
                'title': f"微店商品 {item_id}",
                'english_title': "",
                'description': f"微店商品ID: {item_id}"
            }

            return product_info

        except Exception as e:
            logger.error(f"备用抓取失败: {e}")
            return None

    def download_images(self, image_urls: List[str], save_dir: str, item_id: str) -> List[str]:
        """下载商品图片到本地"""
        import os

        saved_paths = []
        os.makedirs(save_dir, exist_ok=True)

        for i, img_url in enumerate(image_urls[:6]):  # 限制下载前6张图片
            try:
                response = self.session.get(img_url, timeout=10)
                response.raise_for_status()

                # 保存图片
                img_path = os.path.join(save_dir, f"{item_id}_{i}.jpg")
                with open(img_path, 'wb') as f:
                    f.write(response.content)

                saved_paths.append(img_path)
                logger.info(f"图片下载成功: {img_path}")

                # 避免请求过快
                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"图片下载失败 {img_url}: {e}")
                continue

        return saved_paths

    def close(self):
        """关闭资源 - 占位方法"""
        pass

# 全局爬虫实例
_scraper = None

def get_weidian_scraper() -> WeidianScraper:
    """获取微店爬虫实例"""
    global _scraper
    if _scraper is None:
        _scraper = WeidianScraper()
    return _scraper
