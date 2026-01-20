import requests
import re
import json
import time
import logging
from urllib.parse import urlparse, parse_qs, quote
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)

class WeidianScraper:
    """微店商品信息爬虫 - 使用官方API"""

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

        # [新增] 优化连接池，防止多线程抓取时连接数不够
        from requests.adapters import HTTPAdapter
        # 设置连接池大小为 50，重试次数 3
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=3)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        # 修复：更新 Headers，完全匹配你的 CURL 请求
        self.session.headers.update({
            'accept': 'application/json, */*',  # 注意：curl中是 application/json, / 但实际应该是 /*
            'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
            'origin': 'https://weidian.com',
            'priority': 'u=1, i',
            'referer': 'https://weidian.com/',
            'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        })

        # 修复：更新 Cookies
        self.session.cookies.update({
            'wdtoken': '8ea9315c',
            '__spider__visitorid': '0dcf6a5b878847ec',
            'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
            'v-components/cpn-coupon-dialog@nologinshop': '6',
            '__spider__sessionid': 'e0e858ac8efb20a2'
        })

    def _request_with_retry(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: int = 10,
        max_retries: int = 3,
        backoff: float = 0.5
    ) -> Optional[requests.Response]:
        last_error = None
        current_timeout = timeout if isinstance(timeout, tuple) else (5, 10)
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    cookies=cookies,
                    timeout=current_timeout,
                    proxies={'http': None, 'https': None}
                )
                response.raise_for_status()
                return response
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(backoff * attempt)
                else:
                    logger.debug(f"请求失败({max_retries}次): {url} | {e}")
        return None

    def _request_json_with_retry(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: int = 10,
        max_retries: int = 3,
        backoff: float = 0.5
    ) -> Optional[Dict]:
        last_error = None
        current_timeout = timeout if isinstance(timeout, tuple) else (5, 10)
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    cookies=cookies,
                    timeout=current_timeout,
                    proxies={'http': None, 'https': None}
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(backoff * attempt)
                else:
                    logger.debug(f"JSON请求失败({max_retries}次): {url} | {e}")
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

            logger.debug(f"开始抓取商品: {item_id}")

            # 获取店铺信息
            shop_name = self._get_shop_name(url)
            if shop_name == "未知店铺":
                logger.debug("店铺名称获取失败，尝试从页面HTML提取")
                try:
                    page_response = self._request_with_retry(url, timeout=10, headers={
                        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                        'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                        'cache-control': 'max-age=0',
                        'referer': 'https://weidian.com/?userid=1713062461&wfr=c&source=home_shop&ifr=itemdetail&sfr=app&tabType=all',
                        'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"macOS"',
                        'sec-fetch-dest': 'document',
                        'sec-fetch-mode': 'navigate',
                        'sec-fetch-site': 'same-origin',
                        'sec-fetch-user': '?1',
                        'upgrade-insecure-requests': '1',
                        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
                    }, cookies={
                        'wdtoken': '8ea9315c',
                        '__spider__visitorid': '0dcf6a5b878847ec',
                        'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                        'v-components/cpn-coupon-dialog@nologinshop': '10',
                        '__spider__sessionid': 'e55c6458ac1fdba4'
                    })

                    if page_response and page_response.status_code == 200:
                        # 尝试从JavaScript数据中提取店铺名称
                        shop_name_pattern = r'"shopName"[^:]*:[^"]*"([^"]+)"'
                        match = re.search(shop_name_pattern, page_response.text, re.DOTALL | re.IGNORECASE)
                        if match:
                            shop_name = match.group(1).strip()
                            logger.debug(f"✅ 从JavaScript数据获取到店铺名称: {shop_name}")
                except Exception as e:
                    logger.warning(f"从页面提取店铺名称失败: {e}")

            # 使用官方API获取商品信息
            product_info = self._scrape_by_api(item_id, url, shop_name)
            if product_info:
                logger.debug(f"✅ 商品信息抓取成功: {product_info.get('title', 'Unknown')}")
                return product_info

            # 如果API失败，返回None
            logger.error("API抓取失败，没有备用方法")
            return None

        except Exception as e:
            logger.error(f"商品信息抓取失败: {e}")
            return None

    def _scrape_by_api(self, item_id: str, url: str, shop_name: str = '') -> Optional[Dict]:
        """使用微店官方API抓取商品信息"""
        try:
            # 获取商品标题和SKU信息
            title_info = self._get_item_title_and_sku(item_id)
            title = title_info.get('title', '') if title_info else ''

            # 如果API获取失败，尝试从页面HTML中提取商品标题
            if not title:
                logger.debug("API获取标题失败，尝试从页面HTML提取")
                try:
                    page_response = self._request_with_retry(url, timeout=10, headers={
                        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                        'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                        'cache-control': 'max-age=0',
                        'referer': 'https://weidian.com/?userid=1713062461&wfr=c&source=home_shop&ifr=itemdetail&sfr=app&tabType=all',
                        'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"macOS"',
                        'sec-fetch-dest': 'document',
                        'sec-fetch-mode': 'navigate',
                        'sec-fetch-site': 'same-origin',
                        'sec-fetch-user': '?1',
                        'upgrade-insecure-requests': '1',
                        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
                    }, cookies={
                        'wdtoken': '8ea9315c',
                        '__spider__visitorid': '0dcf6a5b878847ec',
                        'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                        'v-components/cpn-coupon-dialog@nologinshop': '10',
                        '__spider__sessionid': 'e55c6458ac1fdba4'
                    })

                    if page_response and page_response.status_code == 200:
                        # 从页面HTML中提取商品标题
                        title_pattern = r'<span[^>]*class="[^"]*item-name[^"]*"[^>]*>([^<]+)</span>'
                        match = re.search(title_pattern, page_response.text, re.DOTALL | re.IGNORECASE)
                        if match:
                            title = match.group(1).strip()
                            logger.debug(f"✅ 从页面HTML获取到商品标题: {title}")
                        else:
                            title = f'微店商品 {item_id}'
                except Exception as e:
                    logger.warning(f"从页面HTML提取标题失败: {e}")
                    title = f'微店商品 {item_id}'
            else:
                title = title

            # 获取商品图片信息（即使标题获取失败也要尝试获取图片）
            image_info = self._get_item_images(item_id)
            images = image_info if image_info else []

            # 如果既没有标题也没有图片，返回None
            if not title and not images:
                logger.error("无法获取商品标题和图片信息")
                return None

            # 构建商品信息
            product_info = {
                'id': item_id,
                'weidian_url': url,
                'cnfans_url': f"https://cnfans.com/product?id={item_id}&platform=WEIDIAN",
                'acbuy_url': f"https://www.acbuy.com/product?url=https%253A%252F%252Fweidian.com%252Fitem.html%253FitemID%253D{item_id}%2526spider_token%253D43fe&id={item_id}&source=WD",
                'images': images,
                'title': title,
                'english_title': self._generate_english_title(title),
                'description': f"微店商品ID: {item_id}",
                'shop_name': shop_name
            }

            return product_info

        except Exception as e:
            logger.error(f"API抓取失败: {e}")
            return None

    def _get_item_title_and_sku(self, item_id: str) -> Optional[Dict]:
        """获取商品标题和SKU信息"""
        try:
            # 构造API URL - 使用更新的格式
            param = json.dumps({"itemId": item_id})
            encoded_param = quote(param)
            timestamp = int(time.time() * 1000)

            api_url = f"https://thor.weidian.com/detail/getItemSkuInfo/1.0?param={encoded_param}&wdtoken=8ea9315c&_={timestamp}"

            logger.debug(f"调用SKU API: {api_url}")

            # 使用与前端 fetch 完全一致的 headers
            headers = {
                "accept": "application/json, */*",
                "accept-language": "en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6",
                "priority": "u=1, i",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "referrer": "https://weidian.com/",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
            }

            # 不带 cookies 发送请求 (有时候 cookies 会导致校验失败)
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                data = self._request_json_with_retry(api_url, headers=headers, timeout=15, max_retries=1)
                if not data:
                    time.sleep(0.3 * attempt)
                    continue

                logger.debug(f"标题API返回状态: {data.get('status', {}).get('code')}")

                if data.get('status', {}).get('code') == 0:
                    result = data.get('result', {})
                    title = result.get('itemTitle', '')
                    if title:
                        return {'title': title, 'sku_info': result}

                time.sleep(0.3 * attempt)

            return None

        except Exception as e:
            logger.error(f"获取商品标题失败: {e}")
            return None

    def _get_item_images(self, item_id: str) -> List[str]:
        """获取商品图片信息 - 同时调用两个API并去重"""
        try:
            all_images = []

            # 1. 获取商品详情图片 (原有API)
            detail_images = self._get_detail_images(item_id)
            all_images.extend(detail_images)

            # 2. 获取SKU属性图片 (新API)
            sku_images = self._get_sku_images(item_id)
            all_images.extend(sku_images)

            # 3. 简单URL去重
            unique_images = []
            seen_urls = set()
            for img_url in all_images:
                if img_url and img_url not in seen_urls:
                    unique_images.append(img_url)
                    seen_urls.add(img_url)

            logger.debug(f"✅ 商品 {item_id} 图片获取完成: 共 {len(unique_images)} 张 (详情:{len(detail_images)}, SKU:{len(sku_images)})")
            if len(unique_images) > 0:
                logger.debug(f"📸 图片URL样例: {unique_images[:3]}")
            return unique_images

        except Exception as e:
            logger.error(f"获取商品图片失败: {e}")
            return []

    def _get_detail_images(self, item_id: str) -> List[str]:
        """获取商品详情图片 (原有API)"""
        try:
            # 构造API URL
            param = json.dumps({"vItemId": item_id})
            encoded_param = quote(param)
            timestamp = int(time.time() * 1000)

            api_url = f"https://thor.weidian.com/detail/getDetailDesc/1.0?param={encoded_param}&wdtoken=8ea9315c&_={timestamp}"

            logger.debug(f"调用详情图片API: {api_url}")

            # 使用更稳定的请求头，模拟浏览器行为
            import requests
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'origin': 'https://weidian.com',
                'priority': 'u=1, i',
                'referer': 'https://weidian.com/',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
            }

            # 设置cookies
            cookies = {
                'wdtoken': '8ea9315c',
                '__spider__visitorid': '0dcf6a5b878847ec',
                'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                'v-components/cpn-coupon-dialog@nologinshop': '10',
                '__spider__sessionid': 'e55c6458ac1fdba4'
            }

            data = self._request_json_with_retry(
                api_url,
                headers=headers,
                cookies=cookies,
                timeout=15,
                max_retries=5
            )
            if not data:
                return []
            logger.debug(f"详情图片API返回状态: {data.get('status', {}).get('code')}")

            images = []
            if data.get('status', {}).get('code') == 0:
                item_detail = data.get('result', {}).get('item_detail', {})
                desc_content = item_detail.get('desc_content', [])

                for item in desc_content:
                    if item.get('type') == 2 and item.get('url'):
                        images.append(item['url'])

            return images

        except Exception as e:
            logger.error(f"获取详情图片失败: {e}")
            return []

    def _get_sku_images(self, item_id: str) -> List[str]:
        """获取SKU属性图片 (新API + attrList解析)"""
        try:
            logger.debug(f"开始获取SKU图片，商品ID: {item_id}")
            title_info = self._get_item_title_and_sku(item_id)
            if not title_info or 'sku_info' not in title_info:
                logger.warning(f"无法获取SKU信息，跳过图片提取: {item_id}")
                return []

            result = title_info['sku_info']
            images = []
            seen_urls = set()

            # 1. 尝试从 attrList 中提取 (这是你提供的JSON中的结构)
            attr_list = result.get('attrList', [])
            if attr_list:
                logger.debug(f"解析 attrList，共 {len(attr_list)} 组属性")
                for attr in attr_list:
                    attr_values = attr.get('attrValues', [])
                    for val in attr_values:
                        img_url = val.get('img')
                        if img_url:
                            # 修复 URL 格式
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url

                            if img_url not in seen_urls:
                                images.append(img_url)
                                seen_urls.add(img_url)

            # 2. 尝试从 skuInfos 中提取 (作为补充)
            sku_infos = result.get('skuInfos', [])
            if sku_infos:
                logger.debug(f"解析 skuInfos，共 {len(sku_infos)} 个SKU")
                for sku in sku_infos:
                    # 注意：skuInfo 对象可能嵌套
                    info = sku.get('skuInfo', {})
                    img_url = info.get('img')
                    if img_url:
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        if img_url not in seen_urls:
                            images.append(img_url)
                            seen_urls.add(img_url)

            logger.debug(f"从SKU属性中成功提取 {len(images)} 张图片")
            return images
        except Exception as e:
            logger.error(f"获取SKU图片失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
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

            response = self.session.get(url, params=params, timeout=10, proxies={'http': None, 'https': None})
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

            response = self.session.get(url, params=params, timeout=10, proxies={'http': None, 'https': None})
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


    def download_images(self, image_urls: List[str], save_dir: str, item_id: str) -> List[str]:
        """多线程下载商品图片到本地"""
        import os
        import concurrent.futures
        import threading

        saved_paths = []
        os.makedirs(save_dir, exist_ok=True)

        # 移除图片数量限制，抓取所有可用的图片
        # SKU图片通常排在详情图之后，现在可以获取所有图片
        logger.debug(f"准备下载 {len(image_urls)} 张图片（无数量限制）")

        def download_single_image(args):
            """下载单张图片的函数"""
            i, img_url = args
            try:
                # 为每个线程创建独立的session
                thread_session = requests.Session()
                thread_session.headers.update(self.session.headers)
                thread_session.cookies.update(self.session.cookies)

                response = thread_session.get(img_url, timeout=10, proxies={'http': None, 'https': None})
                response.raise_for_status()

                # 保存图片
                img_path = os.path.join(save_dir, f"{item_id}_{i}.jpg")
                with open(img_path, 'wb') as f:
                    f.write(response.content)

                logger.debug(f"图片下载成功: {img_path}")
                return img_path

            except Exception as e:
                logger.warning(f"图片下载失败 {img_url}: {e}")
                return None

        # 使用线程池并发下载图片
        try:
            from config import config
        except ImportError:
            from .config import config
        max_workers = min(config.DOWNLOAD_THREADS, len(image_urls))  # 使用配置的下载线程数

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有下载任务
            future_to_image = {
                executor.submit(download_single_image, (i, img_url)): (i, img_url)
                for i, img_url in enumerate(image_urls)
            }

            # 收集结果
            for future in concurrent.futures.as_completed(future_to_image):
                result = future.result()
                if result:
                    saved_paths.append(result)

        # 按索引排序结果
        saved_paths.sort(key=lambda x: int(x.split('_')[-1].split('.')[0]))

        return saved_paths

    def _get_shop_name(self, url: str) -> str:
        """从商品页面获取店铺名称"""
        try:
            logger.debug(f"开始获取店铺名称: {url}")

            # 使用专门的HTML请求headers（不同于API请求的headers）
            html_headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'cache-control': 'max-age=0',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
            }

            html_cookies = {
                'wdtoken': '8ea9315c',
                '__spider__visitorid': '0dcf6a5b878847ec',
                'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                '__spider__sessionid': '4cb270eb969f316c'
            }

            # 请求商品页面（使用HTML专用headers）
            response = self._request_with_retry(
                url,
                headers=html_headers,
                cookies=html_cookies,
                timeout=10,
                max_retries=5
            )
            if not response:
                return "未知店铺"

            # 解码HTML实体（&#34; -> " 等）
            html_content = response.text
            html_content = html_content.replace('&#34;', '"').replace('&#39;', "'").replace('&quot;', '"')

            # 首先尝试最精确的匹配：em标签中的shop-name-str类（根据用户提供的HTML结构）
            shop_name_pattern1 = r'<em[^>]*class="[^"]*\bshop-name-str\b[^"]*"[^>]*>([^<]+)</em>'
            match = re.search(shop_name_pattern1, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (em shop-name-str): {shop_name}")
                return shop_name

            # 然后尝试更宽泛的匹配，查找包含shop-name-str类的任何元素
            shop_name_pattern2 = r'<[^>]*class="[^"]*\bshop-name-str\b[^"]*"[^>]*>([^<]+)</[^>]*>'
            match = re.search(shop_name_pattern2, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (通用shop-name-str): {shop_name}")
                return shop_name

            # 尝试匹配class="shop-name-str"的元素（不限定标签类型）
            shop_name_pattern3 = r'class="shop-name-str"[^>]*>([^<]+)</'
            match = re.search(shop_name_pattern3, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (shop-name-str): {shop_name}")
                return shop_name

            # 尝试从JavaScript数据中提取店铺名称（多种格式）
            # 格式1: "shopName":"Aiseo"
            shop_name_pattern4 = r'"shopName"\s*:\s*"([^"]+)"'
            match = re.search(shop_name_pattern4, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (JavaScript): {shop_name}")
                return shop_name

            # 格式2: \"shopName\":\"Aiseo\" (在HTML中被转义)
            shop_name_pattern5 = r'\\"shopName\\"\s*:\s*\\"([^\\"]+)\\"'
            match = re.search(shop_name_pattern5, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (JavaScript转义): {shop_name}")
                return shop_name

            # 格式3: shopName:"Aiseo" (无引号)
            shop_name_pattern6 = r'shopName\s*:\s*"([^"]+)"'
            match = re.search(shop_name_pattern6, html_content, re.DOTALL | re.IGNORECASE)
            if match:
                shop_name = match.group(1).strip()
                logger.debug(f"✅ 获取到店铺名称 (JavaScript无引号): {shop_name}")
                return shop_name

            logger.warning("未找到店铺名称，使用默认名称")
            return "未知店铺"

        except Exception as e:
            logger.error(f"获取店铺名称失败: {e}")
            return "未知店铺"

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
