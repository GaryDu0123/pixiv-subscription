import base64
import os
import json
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Union, Any, Coroutine
import nonebot
from hoshino import Service, priv
from hoshino.typing import CQEvent
from pixivpy3 import AppPixivAPI
from .config import PROXY_URL, MAX_DISPLAY_WORKS, IMAGE_QUALITY, CHECK_INTERVAL_HOURS, ENABLE_FOLLOWING_SUBSCRIPTION, \
    ENABLE_PIXEL_NOISE, UGOIRA_IMAGE_MODE, UGOIRA_IMAGE_SIZE_LIMIT
import aiohttp
import zipfile
import io
from PIL import Image  # 新增：用于GIF合成
import random
from .utils import send_to_group

# 插件配置
PIXIV_REFRESH_TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'refresh-token.json')
PIXIV_SUBSCRIPTION_PATH = os.path.join(os.path.dirname(__file__), 'subscriptions.json')


if IMAGE_QUALITY not in ['large', 'medium', 'square_medium', 'original']:
    IMAGE_QUALITY = 'large'  # 默认值

HELP_TEXT = """
🎨 pixiv画师订阅插件
[pixiv订阅画师 画师ID/主页URL] 订阅画师
[pixiv取消订阅 画师ID/主页URL] 取消订阅画师  
[pixiv订阅列表] 查看订阅列表
[pixiv开启r18] 允许推送R18内容
[pixiv关闭r18] 屏蔽R18内容
[pixiv屏蔽tag tag名] 屏蔽包含指定tag的作品
[pixiv取消屏蔽tag tag名] 取消屏蔽指定tag
[pixiv开启关注推送] 订阅机器人账号关注的全部画师
[pixiv关闭关注推送] 取消订阅机器人账号关注的画师
[pixiv群设置] 查看当前群的设置
""".strip()

# 创建服务
sv = Service('pixiv-subscription', help_=HELP_TEXT, enable_on_default=True)


def tweak_pil_image(img: Image.Image) -> Image.Image:
    """
    轻微修改图片的一个像素，让同一张图的字节流不完全相同。

    """
    try:
        if img.mode not in ("RGB", "RGBA", "P"):
            return img

        # 做一个拷贝，避免调用方原对象被部分修改
        new_img = img.copy()
        pixels = new_img.load()
        if pixels is None:
            return img

        width, height = new_img.size
        if width <= 0 or height <= 0:
            return img

        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)

        if new_img.mode in ("RGB", "RGBA"):
            px = pixels[x, y]
            if new_img.mode == "RGB":
                r, g, b = px
                pixels[x, y] = ((r + 1) % 256, g, b)
            else:
                r, g, b, a = px
                pixels[x, y] = ((r + 1) % 256, g, b, a)
        elif new_img.mode == "P":
            val = pixels[x, y]
            pixels[x, y] = (val + 1) % 256

        return new_img
    except Exception as e:
        sv.logger.error(f"修改图片像素失败: {e}")
        return img

class PixivSubscriptionManager:
    def __init__(self):
        self.api = None
        self.subscriptions = self.load_subscriptions()
        self.refresh_token = self.load_refresh_token()
        self.init_api()
        sv.logger.info("正在使用refresh_token登录Pixiv...")
        status, msg = self.login(self.refresh_token)
        sv.logger.info(msg)

    @staticmethod
    def load_refresh_token() -> str:
        """加载refresh_token"""
        if os.path.exists(PIXIV_REFRESH_TOKEN_PATH):
            with open(PIXIV_REFRESH_TOKEN_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('refresh_token', "")
        return ""

    def save_refresh_token(self):
        """保存更新的refresh_token"""
        with open(PIXIV_REFRESH_TOKEN_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                'refresh_token': self.refresh_token
            }, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_subscriptions() -> Dict:
        """加载订阅数据"""
        if os.path.exists(PIXIV_SUBSCRIPTION_PATH):
            with open(PIXIV_SUBSCRIPTION_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_subscriptions(self) -> None:
        """保存订阅数据"""
        with open(PIXIV_SUBSCRIPTION_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)

    def init_api(self) -> None:
        """初始化API"""
        try:
            # 准备请求参数
            kwargs = {}
            if PROXY_URL:
                kwargs['proxies'] = {
                    'https': PROXY_URL,
                    'http': PROXY_URL
                }

            self.api = AppPixivAPI(**kwargs)
            sv.logger.info("Pixiv API 初始化完成")
        except Exception as e:
            sv.logger.error(f"初始化 Pixiv API 失败: {e}")

    def login(self, refresh_token: str = None) -> Tuple[bool, str]:
        """使用refresh_token登录pixiv"""
        # 如果提供了新的refresh_token，则更新配置
        if refresh_token:
            self.refresh_token = refresh_token
            self.save_refresh_token()

        if not self.refresh_token:
            return False, "未设置refresh_token"

        try:
            self.api.auth(refresh_token=self.refresh_token)
            return True, "Pixiv登录成功"
        except Exception as e:
            return False, f"Pixiv登录失败: {e}"

    def ensure_group_settings(self, group_id: str) -> None:
        """确保群设置存在"""
        if group_id not in self.subscriptions:
            self.subscriptions[group_id] = {
                'artists': [],
                'r18_enabled': False,
                'blocked_tags': [],
                'push_following_enabled': False
            }
        # 兼容旧配置，如果旧配置没有这个键则添加默认值
        elif 'push_following_enabled' not in self.subscriptions[group_id]:
            self.subscriptions[group_id]['push_following_enabled'] = False

    def add_subscription(self, group_id: str, user_id: str) -> bool:
        """添加订阅"""
        self.ensure_group_settings(group_id)

        if user_id not in self.subscriptions[group_id]['artists']:
            self.subscriptions[group_id]['artists'].append(user_id)
            self.save_subscriptions()
            return True
        return False

    def remove_subscription(self, group_id: str, user_id: str) -> bool:
        """取消订阅"""
        if group_id in self.subscriptions and user_id in self.subscriptions[group_id]['artists']:
            self.subscriptions[group_id]['artists'].remove(user_id)
            self.save_subscriptions()
            return True
        return False

    def get_subscriptions(self, group_id: str) -> List[str]:
        """获取群订阅列表"""
        if group_id in self.subscriptions:
            return self.subscriptions[group_id]['artists']
        return []

    def set_r18_enabled(self, group_id: str, enabled: bool) -> None:
        """设置群的R18开关"""
        self.ensure_group_settings(group_id)
        self.subscriptions[group_id]['r18_enabled'] = enabled
        self.save_subscriptions()

    def is_r18_enabled(self, group_id: str) -> bool:
        """检查群是否开启R18"""
        if group_id in self.subscriptions:
            return self.subscriptions[group_id].get('r18_enabled', False)
        return False

    def set_push_following(self, group_id: str, enabled: bool) -> None:
        """设置群的 关注画师推送 开关"""
        self.ensure_group_settings(group_id)
        self.subscriptions[group_id]['push_following_enabled'] = enabled
        self.save_subscriptions()

    def is_push_following_enabled(self, group_id: str) -> bool:
        """检查群是否开启了 关注画师推送"""
        if group_id in self.subscriptions:
            return self.subscriptions[group_id].get('push_following_enabled', False)
        return False

    def add_blocked_tag(self, group_id: str, tag: str) -> bool:
        """添加屏蔽tag"""
        self.ensure_group_settings(group_id)

        if tag not in self.subscriptions[group_id]['blocked_tags']:
            self.subscriptions[group_id]['blocked_tags'].append(tag)
            self.save_subscriptions()
            return True
        return False

    def remove_blocked_tag(self, group_id: str, tag: str) -> bool:
        """移除屏蔽tag"""
        if (group_id in self.subscriptions and
                tag in self.subscriptions[group_id]['blocked_tags']):
            self.subscriptions[group_id]['blocked_tags'].remove(tag)
            self.save_subscriptions()
            return True
        return False

    def get_blocked_tags(self, group_id: str) -> List[str]:
        """获取群的屏蔽tag列表"""
        if group_id in self.subscriptions:
            return self.subscriptions[group_id].get('blocked_tags', [])
        return []

    def get_group_settings(self, group_id: str) -> Dict:
        """获取群设置"""
        self.ensure_group_settings(group_id)
        return self.subscriptions[group_id]


    def is_illust_allowed(self, illust: dict, group_id: Union[str, int]) -> bool:
        """检查作品是否允许在指定群推送"""
        if isinstance(group_id, int):
            group_id = str(group_id)
        # 检查R18限制
        if not self.is_r18_enabled(group_id):
            # x_restrict: 0=全年龄, 1=R18, 2=R18G
            x_restrict = illust.get('x_restrict', 0)
            if x_restrict != 0:
                return False

        # 检查屏蔽tag
        blocked_tags = self.get_blocked_tags(group_id)
        if blocked_tags:
            illust_tags = []
            if 'tags' in illust:
                illust_tags = [tag.get('name', '').lower() for tag in illust['tags']]
                # 也检查翻译后的tag
                for tag in illust['tags']:
                    if 'translated_name' in tag and tag['translated_name']:
                        illust_tags.append(tag['translated_name'].lower())

            # 检查是否包含屏蔽的tag（不区分大小写）
            for blocked_tag in blocked_tags:
                if blocked_tag.lower() in illust_tags:
                    return False

        return True

    async def get_user_info(self, user_id: str):
        """获取用户信息"""
        result = None
        try:
            result = await self.__exec_and_retry_with_login(
                self.api.user_detail,
                user_id
            )
            if 'error' in result or 'user' not in result: # 表示请求失败
                raise ValueError(result)
            if result and result.get('user'):
                return result['user']
        except Exception as e:
            sv.logger.error(f"获取用户信息失败: {e}; Return response:{result}")
        return None

    async def get_new_illusts_with_user_info(self, user_id: str, start_time: datetime, interval_hours: float) -> Tuple[
        Dict, List[Dict]]:
        """获取指定时间窗口内的新作品, 返回查询的用户信息和新作品列表"""
        try:
            # 计算检查的时间范围
            check_start = start_time - timedelta(hours=interval_hours)
            check_end = start_time


            # 默认会返回30个作品, 足够大多数场景使用
            result = await self.__exec_and_retry_with_login(
                self.api.user_illusts,
                user_id
            )

            if not result or 'illusts' not in result or not result['illusts'] or 'user' not in result or not result[
                'user']:
                raise ValueError(result)

            new_illusts = []
            for illust in result['illusts']:
                try:
                    # 直接解析并转换为UTC
                    create_date_utc = datetime.fromisoformat(illust['create_date']).astimezone(timezone.utc)

                    # 检查作品是否在时间窗口内
                    if check_start < create_date_utc <= check_end:
                        new_illusts.append(illust)
                    elif create_date_utc <= check_start:
                        # 由于作品按时间倒序排列，如果当前作品已经超出时间范围，后续作品也会超出
                        break

                except (ValueError, TypeError) as e:
                    sv.logger.error(f"解析时间失败: {e}, 原始时间: {illust.get('create_date', 'unknown')}")
                    continue

            return result['user'], new_illusts

        except Exception as e:
            sv.logger.error(f"获取作品列表失败: {e}")
            return {}, []

    async def get_illust_by_id(self, illust_id: str) -> Dict:
        """根据作品ID获取作品详情"""
        try:
            result = await self.__exec_and_retry_with_login(
                self.api.illust_detail,
                illust_id
            )
            if not result or 'illust' not in result or not result['illust']:
                raise ValueError(result)
            return result['illust']
        except Exception as e:
            sv.logger.error(f"获取作品详情失败: {e}")
            return {}

    async def get_ranking(self, mode: str) -> Union[Dict[Any, Any]]:
        """
        用于获取并发送指定模式的排行榜。
        :param mode: 排行榜模式 (e.g., 'day', 'week_r18')
        """
        try:
            result = await self.__exec_and_retry_with_login(
                self.api.illust_ranking,
                mode
            )

            if not isinstance(result, dict) or 'illusts' not in result or not result['illusts']:
                sv.logger.error(f"获取Pixiv排行榜失败 '{mode}': {result}")
                return {}

            # 成功获取，返回作品列表
            return result.get('illusts', {})

        except Exception as e:
            # 捕获其他意外错误，例如网络问题
            sv.logger.error(f"获取Pixiv排行榜时发生未知异常 '{mode}': {e}")
            return {}

    async def user_illusts(self, user_id: Union[str, int]):
        """
        获取指定用户的作品列表, api限制默认获取前30个作品
        :param user_id: 画师用户ID
        """
        try:
            result = await self.__exec_and_retry_with_login(
                self.api.user_illusts,
                user_id
            )

            if not isinstance(result, dict) or 'illusts' not in result or not result['illusts']:
                sv.logger.error(f"获取Pixiv用户作品列表失败 '{user_id}': {result}")
                return {}, {}

            # 成功获取，返回作品列表
            return result.get('illusts', {}), result.get('user', {})
        except Exception as e:
            sv.logger.error(f"获取Pixiv用户作品列表时发生未知异常 '{user_id}': {e}")
            return {}, {}

    async def get_illust_follow(self, start_time: datetime, interval_hours: float) -> List[Dict]:
        """
        获取当前bot关注画师在指定时间窗口内的新作品。
        API本身返回最近作品，此函数在此基础上进行时间过滤。
        """
        try:
            # 调用API获取原始的关注动态列表
            result = await self.__exec_and_retry_with_login(
                self.api.illust_follow
            )

            # 检查API返回是否有效
            if not isinstance(result, dict) or 'illusts' not in result or not result.get('illusts'):
                sv.logger.error(f"获取Pixiv关注作品列表失败或列表为空: {result}")
                return []  # 失败或无内容时返回空列表

            # 准备时间和用于存放结果的容器
            check_start = start_time - timedelta(hours=interval_hours)
            check_end = start_time
            new_illusts_in_window = []

            # 遍历API返回的所有作品，并根据时间窗口进行过滤
            for illust in result['illusts']:
                try:
                    # 解析作品创建时间字符串
                    create_date_utc = datetime.fromisoformat(illust['create_date']).astimezone(timezone.utc)

                    # 判断作品是否在检查时间窗口内
                    if check_start < create_date_utc <= check_end:
                        new_illusts_in_window.append(illust)

                except (ValueError, TypeError, KeyError) as e:
                    sv.logger.warning(f"解析或过滤关注作品时跳过一个项目: {e}, 作品ID: {illust.get('id')}")
                    continue
            # 返回经过时间过滤后的新作品列表
            return new_illusts_in_window

        except Exception as e:
            sv.logger.error(f"获取Pixiv关注作品时发生未知异常: {e}")
            return []  # 确保任何未知异常都返回一个安全的空列表

    @staticmethod
    async def download_image_as_base64(url: str) -> str:
        """下载图片并转换为base64编码（可选进行轻微像素修改）"""
        try:
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            async with aiohttp.ClientSession(
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.get(url, proxy=PROXY_URL) as resp:
                    if resp.status != 200:
                        sv.logger.error(f"下载图片失败, HTTP {resp.status}: {url}")
                        return ""

                    raw_data = await resp.read()

                    # 如果禁用了图片修改，直接返回原图base64
                    if not ENABLE_PIXEL_NOISE:
                        return base64.b64encode(raw_data).decode("utf-8")

                    # 进行轻微像素修改防止风控
                    try:
                        img = Image.open(io.BytesIO(raw_data))
                        mutated = tweak_pil_image(img)
                        buf = io.BytesIO()
                        fmt = mutated.format or img.format or "PNG"
                        mutated.save(buf, format=fmt)
                        processed_bytes = buf.getvalue()
                    except Exception as e:
                        sv.logger.error(f"图片处理异常: {e}, URL: {url}")
                        processed_bytes = raw_data
                    return base64.b64encode(processed_bytes).decode("utf-8")

        except Exception as e:
            sv.logger.error(f"下载图片异常: {e}, URL: {url}")
            return ""

    @staticmethod
    def get_image_urls(illust: dict) -> List[str]:
        """
        获取作品的所有图片URL,
        """
        urls: List[str] = []
        page_count = illust.get('page_count', 1)

        def get_image_url(image_urls: dict) -> str:
            """
            根据 IMAGE_QUALITY 获取单张图片URL的辅助函数
            """
            if not image_urls:
                return ""
            check_order = [IMAGE_QUALITY, 'large', 'medium', 'square_medium']

            for quality in check_order:
                u = image_urls.get(quality)
                if u:
                    return u
            return ""

        if page_count > 1:
            # 多图情况下, 从 meta_pages 中逐页获取
            meta_pages = illust.get('meta_pages') or []
            for page in meta_pages:
                url = get_image_url(page.get('image_urls', {}))
                if url:
                    urls.append(url)
        else:
            # 单页, 图片信息在 meta_single_page
            meta_single_page = illust.get('meta_single_page', {})
            url = meta_single_page.get('original_image_url')
            if url:
                urls.append(url)
        return urls

    # 新方法：下载Ugoira并合成GIF base64
    # 下载Ugoira并合成GIF base64
    @staticmethod
    async def _download_ugoira_zip(zip_url: str) -> bytes:
        """辅助方法：下载Ugoira的ZIP文件"""
        headers = {
            'Referer': 'https://www.pixiv.net/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.get(zip_url, proxy=PROXY_URL) as resp:
                    if resp.status != 200:
                        sv.logger.error(f"下载Ugoira ZIP失败, HTTP {resp.status}: {zip_url}")
                        return b""
                    return await resp.read()
        except Exception as e:
            sv.logger.error(f"下载ZIP网络异常: {e}, URL: {zip_url}")
            return b""

    @staticmethod
    def _process_ugoira_zip_to_gif(zip_data: bytes, frames_info: list) -> bytes:
        """辅助方法：解压ZIP并合成GIF"""
        MAX_FRAMES = 600

        try:
            with io.BytesIO(zip_data) as zip_buffer:
                with zipfile.ZipFile(zip_buffer) as zip_file:
                    # 获取并排序帧文件
                    frame_files = sorted(
                        [f for f in zip_file.namelist() if f.endswith(('.jpg', '.png'))]
                    )[:MAX_FRAMES]

                    if not frame_files:
                        return b""

                    images: List[Image.Image] = []
                    durations: List[int] = []

                    # 读取所有帧
                    for i, frame_name in enumerate(frame_files):
                        with zip_file.open(frame_name) as frame_file:
                            img = Image.open(io.BytesIO(frame_file.read()))
                            images.append(img)
                        # 获取这一帧的持续时间
                        duration = frames_info[i]['delay'] if i < len(frames_info) else 100
                        durations.append(duration)

                    # 像素修改防止图片被夹
                    if ENABLE_PIXEL_NOISE:
                        try:
                            if images:
                                frame_idx = random.randint(0, len(images) - 1)
                                images[0] = tweak_pil_image(images[0])
                                images[frame_idx] = tweak_pil_image(images[frame_idx])
                                sv.logger.info(f"已修改Ugoira帧 {frame_idx} 的像素")
                        except Exception as e:
                            sv.logger.error(f"Ugoira像素修改失败: {e}")

                    # 合成GIF
                    gif_buffer = io.BytesIO()
                    if UGOIRA_IMAGE_MODE.upper() == 'WEBP':
                        images[0].save(
                            gif_buffer,
                            format='WEBP',
                            save_all=True,
                            append_images=images[1:],
                            duration=durations,
                            loop=0,
                            quality=90,
                            method=1
                        )
                    else:
                        images[0].save(
                            gif_buffer,
                            format='GIF',
                            save_all=True,
                            append_images=images[1:],
                            duration=durations,
                            loop=0
                        )

                    return gif_buffer.getvalue()

        except zipfile.BadZipFile:
            sv.logger.error("ZIP文件损坏")
        except Exception as e:
            sv.logger.error(f"GIF合成过程异常: {e}")

        return b""

    async def download_ugoira_as_gif_base64(self, illust) -> str:
        """主方法：下载Ugoira ZIP，合成GIF，转为base64"""
        illust_id = illust.get('id')
        if not illust_id:
            return ""

        # 获取pixiv动图元数据
        try:
            metadata = await self.__exec_and_retry_with_login(
                self.api.ugoira_metadata,
                illust_id
            )
        except Exception as e:
            sv.logger.error(f"获取 Ugoira 元数据异常: {e}")
            return ""

        if not metadata or 'ugoira_metadata' not in metadata:
            sv.logger.error(f"获取 Ugoira 元数据失败: {illust_id}")
            return ""

        u_meta = metadata['ugoira_metadata']
        zip_urls = u_meta.get('zip_urls', {})
        zip_url = zip_urls.get('medium') or zip_urls.get('original')

        # 检查URL有效性，无效则回退到静态图
        if not zip_url or not zip_url.endswith('.zip'):
            sv.logger.error(f"无效的 Ugoira ZIP URL: {zip_url}")
            fallback_url = illust.get('meta_single_page', {}).get('original_image_url')
            if fallback_url:
                return await self.download_image_as_base64(fallback_url)
            return ""

        # 下载ZIP
        zip_data = await self._download_ugoira_zip(zip_url)
        if not zip_data:
            return ""

        # 在线程池中处理图像合成, 避免阻塞事件循环
        frames_info = u_meta.get('frames') or []
        gif_bytes = await asyncio.get_event_loop().run_in_executor(
            None,
            self._process_ugoira_zip_to_gif,
            zip_data,
            frames_info
        )

        if not gif_bytes:
            return ""

        # 检查大小限制
        if len(gif_bytes) > UGOIRA_IMAGE_SIZE_LIMIT * 1024 * 1024:
            sv.logger.warning(f"GIF太大 ({len(gif_bytes) / 1024 / 1024:.2f}MB)，回退到第一帧静态图")
            fallback_url = illust.get('meta_single_page', {}).get('original_image_url')
            if fallback_url:
                return await self.download_image_as_base64(fallback_url)
            return ""

        return base64.b64encode(gif_bytes).decode('utf-8')

    @staticmethod
    def is_auth_error(exception) -> bool:
        """判断是否是认证相关的错误"""
        error_msg = str(exception).lower()
        auth_error_keywords = [
            'invalid_grant',
            'invalid_token',
            'unauthorized',
            'oauth',
            'access token',
        ]
        return any(keyword in error_msg for keyword in auth_error_keywords)

    async def __exec_and_retry_with_login(self, api_func, *args, **kwargs):
        """执行 Pixivpy3 API 函数，如果遇到认证错误则自动重新登录并重试一次"""
        result = await asyncio.get_event_loop().run_in_executor(
            None, api_func, *args
        )

        # 检查返回结果是否包含认证错误
        if self.is_auth_error(result):
            # 重新登录
            success, msg = await asyncio.get_event_loop().run_in_executor(
                None, self.login, self.refresh_token
            )
            if success:
                # 重新执行API函数
                result = await asyncio.get_event_loop().run_in_executor(
                    None, api_func, *args
                )
                return result
            else:
                sv.logger.error(f"重新登录失败: {msg}, {api_func}, {args}, {kwargs}无法执行, result: {result}")
                return result  # 返回原始错误结果
        return result

# 创建管理器实例
manager = PixivSubscriptionManager()


@sv.on_prefix('pixiv订阅画师')
async def subscribe_artist(bot, ev: CQEvent):
    """订阅画师"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能订阅画师")
        return

    input_text = ev.message.extract_plain_text().strip()
    if not input_text:
        await bot.send(ev, "请输入画师ID或用户主页链接")
        return

    # 尝试从URL中提取ID
    match = re.search(r'/users/(\d+)', input_text)
    if match:
        user_id = match.group(1)
    else:
        user_id = input_text

    if not user_id.isdigit():
        await bot.send(ev, "无效的画师ID或链接")
        return

    group_id = str(ev.group_id)

    # 检查画师是否存在
    user_info = await manager.get_user_info(user_id)

    if not user_info:
        await bot.send(ev, f"画师ID {user_id} 不存在或无法访问")
        return

    # 添加订阅
    if manager.add_subscription(group_id, user_id):
        await bot.send(ev, f"成功订阅画师: {user_info['name']} ({user_id})")
    else:
        await bot.send(ev, f"画师 {user_info['name']} ({user_id}) 已在订阅列表中")


@sv.on_prefix('pixiv取消订阅')
async def unsubscribe_artist(bot, ev: CQEvent):
    """取消订阅画师"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能取消订阅画师")
        return

    input_text = ev.message.extract_plain_text().strip()
    if not input_text:
        await bot.send(ev, "请输入要取消订阅的画师ID或用户主页链接")
        return

    # 尝试从URL中提取ID
    match = re.search(r'/users/(\d+)', input_text)
    if match:
        user_id = match.group(1)
    else:
        user_id = input_text

    if not user_id.isdigit():
        await bot.send(ev, "无效的画师ID或链接, ID必须为数字。")
        return

    group_id = str(ev.group_id)

    if manager.remove_subscription(group_id, user_id):
        await bot.send(ev, f"已取消订阅画师: {user_id}")
    else:
        await bot.send(ev, f"画师 {user_id} 不在订阅列表中")


@sv.on_prefix('pixiv订阅列表')
async def list_subscriptions(bot, ev: CQEvent):
    """查看订阅列表"""
    group_id = str(ev.group_id)
    subscriptions = manager.get_subscriptions(group_id)

    if not subscriptions:
        await bot.send(ev, "当前群没有订阅任何画师")
        return
    # todo
    # 构建列表：为每个 user_id 获取名字
    sub_list = []
    for user_id in subscriptions:
        user_info = await manager.get_user_info(user_id)
        if user_info and 'name' in user_info:
            name = user_info['name']
            sub_list.append(f"{name}: {user_id}")
        else:
            sub_list.append(f"{user_id}: 未知")  # 回退，如果获取失败
            sv.logger.warning(f"无法获取画师 {user_id} 的信息")

    msg = "当前订阅的画师:\n"
    msg += "\n".join(sub_list)

    await bot.send(ev, msg)


@sv.on_prefix('pixiv重设登录token')
async def set_pixiv_token(bot, ev: CQEvent):
    """设置pixiv refresh_token (仅群主/管理员)"""
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, "只有超级用户才能设置pixiv refresh_token, 请使用来杯咖啡通知维护者")
        return

    refresh_token = ev.message.extract_plain_text().strip()
    if not refresh_token:
        await bot.send(ev, "请输入refresh_token\n例：重设pixiv登录token your_refresh_token")
        return

    success, msg = manager.login(refresh_token)
    await bot.send(ev, msg)

@sv.on_prefix('pixiv开启关注推送')
async def enable_push_following(bot, ev: CQEvent):
    """开启机器人账号关注画师的推送 (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置此项")
        return

    if not ENABLE_FOLLOWING_SUBSCRIPTION:
        await bot.send(ev, "该功能已被维护组全局关闭")
        return

    group_id = str(ev.group_id)
    manager.set_push_following(group_id, True)
    await bot.send(ev, "本群将会收到账号关注画师的更新")

@sv.on_prefix('pixiv关闭关注推送')
async def disable_push_following(bot, ev: CQEvent):
    """关闭机器人账号关注画师的推送 (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置此项")
        return

    group_id = str(ev.group_id)
    manager.set_push_following(group_id, False)
    await bot.send(ev, "已关闭关注推送")

@sv.on_prefix('pixiv开启r18')
async def enable_r18(bot, ev: CQEvent):
    """开启R18内容推送 (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置R18开关")
        return

    group_id = str(ev.group_id)
    manager.set_r18_enabled(group_id, True)
    await bot.send(ev, "已开启R18内容推送")


@sv.on_prefix('pixiv关闭r18')
async def disable_r18(bot, ev: CQEvent):
    """关闭R18内容推送 (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置R18开关")
        return

    group_id = str(ev.group_id)
    manager.set_r18_enabled(group_id, False)
    await bot.send(ev, "已关闭R18内容推送")


@sv.on_prefix('pixiv屏蔽tag')
async def block_tag(bot, ev: CQEvent):
    """屏蔽指定tag (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置屏蔽tag")
        return

    tag = ev.message.extract_plain_text().strip()
    if not tag:
        await bot.send(ev, "请输入要屏蔽的tag\n例：屏蔽tag R-18")
        return

    group_id = str(ev.group_id)
    if manager.add_blocked_tag(group_id, tag):
        await bot.send(ev, f"已屏蔽tag: {tag}")
    else:
        await bot.send(ev, f"tag '{tag}' 已在屏蔽列表中")


@sv.on_prefix('pixiv取消屏蔽tag')
async def unblock_tag(bot, ev: CQEvent):
    """取消屏蔽指定tag (仅管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置屏蔽tag")
        return

    tag = ev.message.extract_plain_text().strip()
    if not tag:
        await bot.send(ev, "请输入要取消屏蔽的tag\n例：取消屏蔽tag R-18")
        return

    group_id = str(ev.group_id)
    if manager.remove_blocked_tag(group_id, tag):
        await bot.send(ev, f"已取消屏蔽tag: {tag}")
    else:
        await bot.send(ev, f"tag '{tag}' 不在屏蔽列表中")


@sv.on_prefix('pixiv群设置')
async def show_group_settings(bot, ev: CQEvent):
    """查看群设置"""
    group_id = str(ev.group_id)
    settings = manager.get_group_settings(group_id)

    msg = "当前群设置:\n"
    msg += f"📋 订阅画师数量: {len(settings['artists'])}\n"
    msg += f"🔞 R18推送: {'开启' if settings['r18_enabled'] else '关闭'}\n"

    if ENABLE_FOLLOWING_SUBSCRIPTION:
        following_status = '开启' if settings.get('push_following_enabled', False) else '关闭'
        msg += f"💖 关注画师推送: {following_status}\n"

    blocked_tags = settings['blocked_tags']
    if blocked_tags:
        msg += f"🚫 屏蔽tag: {', '.join(blocked_tags)}"
    else:
        msg += "🚫 屏蔽tag: 无"

    await bot.send(ev, msg)


@sv.on_prefix('pixiv强制检查')
async def force_check_updates(bot, ev: CQEvent):
    """强制执行一次更新检查 (仅用于测试)"""
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, "只有超级用户才能强制检查更新")
        return

    await bot.send(ev, "开始检查画师更新，请稍候...")

    try:
        # 执行检查更新任务
        await check_updates()
        await bot.send(ev, "✅ 画师更新检查完成")
    except Exception as e:
        sv.logger.error(f"强制检查更新时出错: {e}")
        await bot.send(ev, f"❌ 检查更新时出现错误: {e}")


async def construct_group_messages(artist_name: str, filtered_illusts: List[Dict]) -> List[str]:
    """
    为每批作品构建消息列表，其中每个作品（illust）对应列表中的一个字符串元素。
    - 每个作品的文字描述和其所有图片（或动图）被合并到同一个消息字符串中。
    - 每个作品最多展示 MAX_DISPLAY_WORKS 张图片。
    - 返回一个消息字符串列表，每个字符串代表一个完整的作品推送。
    """
    all_messages = []
    # 对作品按ID升序排序，确保推送时是正序的

    for illust in filtered_illusts:
        illust_id = illust.get('id', 'N/A')
        title = illust.get('title', '无标题')
        tags = [tag.get('name', '') for tag in illust['tags'][:3] if tag.get('name')]
        # link = f"https://www.pixiv.net/artworks/{illust_id}"

        # 构建基础文本消息
        message = (
            f"🎨 {artist_name} 有新作品更新！\n"
            f"📖 {title}\n"
            # f"ID: {illust_id}\n"
            f"🏷️ {', '.join(tags)}"
            # f"链接: {link}"
        )

        # 获取并处理该作品的所有媒体内容
        try:
            illust_type = illust.get('type')
            if illust_type == 'ugoira':
                b64_content = await manager.download_ugoira_as_gif_base64(illust)
                if b64_content:
                    message += f"\n[CQ:image,file=base64://{b64_content}]"

            elif illust_type == 'illust':
                image_urls = manager.get_image_urls(illust)
                urls_to_download = image_urls[:MAX_DISPLAY_WORKS]

                for img_url in urls_to_download:
                    b64_content = await manager.download_image_as_base64(img_url)
                    if b64_content:
                        message += f"\n[CQ:image,file=base64://{b64_content}]"
                    await asyncio.sleep(0.5)  # 避免请求过快

                # 如果图片被截断，在末尾添加提示
                if len(image_urls) > MAX_DISPLAY_WORKS:
                    message += f"该作品共有 {len(image_urls)} 张图片，仅展示前 {MAX_DISPLAY_WORKS} 张。"
        except Exception as e:
            sv.logger.error(f"处理作品 {illust_id} 的媒体时出错: {e}")
            message += "\n(图片处理失败，请查看后台日志)"
        # 将构建完成的单个作品消息添加到最终列表中
        all_messages.append(message.strip())
        await asyncio.sleep(0.5)  # 避免请求过快
    return all_messages


#调整更新发送方式以适应多图分割发送
async def process_and_send_updates(bot, user_id: str, artist_name: str,
                                  new_illusts: List[Dict], target_group_ids: set):
    """
    处理单个画师的更新并发送给所有目标群组。
    根据每个群的设置过滤作品，再构造多条消息逐条发送。
    """
    # 如果没有新作品，直接返回
    if not new_illusts:
        return

    for group_id in target_group_ids:
        try:
            # 针对每个群组，独立过滤作品
            filtered_illusts = [
                illust for illust in new_illusts if manager.is_illust_allowed(illust, group_id)
            ]
            if not filtered_illusts:
                continue

            # 构造所有消息内容
            messages_to_send = await construct_group_messages(artist_name, filtered_illusts)

            # 如果时间窗口内单画师作品过多，合并发送
            if len(filtered_illusts) > 3:
                await send_to_group(bot, group_id, messages_to_send)
            else:
                # 逐条发送
                for msg in messages_to_send:
                    await bot.send_group_msg(group_id=int(group_id), message=msg)
                    await asyncio.sleep(2)  # 防风控延时

        except Exception as e:
            sv.logger.error(f"向群 {group_id} 发送画师 {user_id} ({artist_name}) 更新消息时出错: {e}")
            continue

# todo 处理多图发送
@sv.scheduled_job('interval', hours=CHECK_INTERVAL_HOURS)
async def check_updates():
    """
    发送画师订阅的更新作品到对应群组的任务

    实现思路:
    1. user_follow的获取到的画师更新的作品实际上是和在当前时间窗口内用画师ID获取的作品列表是一样的, 所以需要去重
    2. 根据避免频繁请求API的原则, 对每个画师只请求一次, 也就是说在user_follow推送之后就不需要用画师ID去请求一次了
    3. 构建一个画师ID到订阅群列表的映射表
    4. user_follow获取到时间窗口内的更新之后, 根据群设置过滤内容, 然后根据群是否订阅该画师和是否推送bot关注画师为条件来决定是否发送消息,
        将发送过的画师ID从映射表中删除
    5. 剩下的画师ID再用画师ID去请求一次, 这样就避免了重复请求和重复发送消息的问题
    """
    start_time = datetime.now()

    bot = nonebot.get_bot()

    # 计算本次检查的时间窗口 - 以当前时间为结束点，向前检查CHECK_INTERVAL_HOURS的小时数
    check_time = datetime.now(timezone.utc)

    # 收集所有需要检查的画师ID，并记录画师被哪些群订阅
    artist_to_groups = {}  # {artist_id: [group_id1, group_id2, ...]}

    for group_id, group_data in manager.subscriptions.items():
        artists = group_data.get('artists', [])
        for user_id in artists:
            if user_id not in artist_to_groups:
                artist_to_groups[user_id] = []
            artist_to_groups[user_id].append(group_id)

    # 处理关注推送 (如果开启)
    if ENABLE_FOLLOWING_SUBSCRIPTION:
        groups_enabling_following = {
            group_id for group_id, setting in manager.subscriptions.items()
            if setting.get('push_following_enabled', False)
        }

        # 获取关注画师在时间窗口内的新作品
        followed_illusts = await manager.get_illust_follow(
            start_time=check_time,
            interval_hours=CHECK_INTERVAL_HOURS
        )

        # 按画师ID分组作品
        bot_followed_illusts = {}
        for illust in followed_illusts:
            user_id = str(illust['user']['id'])
            if user_id not in bot_followed_illusts:
                bot_followed_illusts[user_id] = {'user': illust['user'], 'illusts': []}
            bot_followed_illusts[user_id]['illusts'].append(illust)

        # 处理并发送关注画师的更新
        for user_id, data in bot_followed_illusts.items():
            artist_name = data['user']['name']
            new_illusts = data['illusts']

            # 计算需要通知的所有群组：订阅了该画师的 + 开启了全局关注推送的
            target_group_ids = set(artist_to_groups.get(user_id, [])) | groups_enabling_following

            await process_and_send_updates(bot, user_id, artist_name, new_illusts, target_group_ids)

            # 从待检查列表中移除，避免重复请求
            if user_id in artist_to_groups:
                del artist_to_groups[user_id]

    # 处理剩下的、未被关注推送覆盖的画师
    for user_id, group_ids in artist_to_groups.items():
        try:
            user_info, new_illusts = await manager.get_new_illusts_with_user_info(
                user_id,
                start_time=check_time,
                interval_hours=CHECK_INTERVAL_HOURS
            )

            if not new_illusts:
                sv.logger.info(f"画师 {user_id} 没有新作品，跳过")
                await asyncio.sleep(3)
                continue

            artist_name = user_info.get('name', f"画师ID:{user_id}")

            await process_and_send_updates(bot, user_id, artist_name, new_illusts, set(group_ids))

            sv.logger.info(f"画师 {user_id} 处理完成，等待3秒...")
            await asyncio.sleep(3)
        except Exception as e:
            sv.logger.error(f"获取画师 {user_id} 更新时出错: {e}")
            import traceback
            sv.logger.error(f"错误堆栈: {traceback.format_exc()}")
            continue

    end_time = datetime.now()
    duration = end_time - start_time
    sv.logger.info(f"画师订阅检查完成，总耗时: {duration}, 结束时间: {end_time}")
