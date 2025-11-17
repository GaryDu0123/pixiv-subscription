import base64
import os
import json
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
import nonebot
from hoshino import Service, priv
from hoshino.typing import CQEvent
from pixivpy3 import AppPixivAPI
from .config import PROXY_URL, MAX_DISPLAY_WORKS, IMAGE_QUALITY, CHECK_INTERVAL_HOURS
from hoshino.util import DailyNumberLimiter
try:
    from .config import PGET_DAILY_LIMIT
except ImportError:
    PGET_DAILY_LIMIT = 10  # 兼容旧配置
import aiohttp
import zipfile
import io
from PIL import Image  # 新增：用于GIF合成
import random
import uuid

# 插件配置
PIXIV_REFRESH_TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'refresh-token.json')
PIXIV_SUBSCRIPTION_PATH = os.path.join(os.path.dirname(__file__), 'subscriptions.json')
pget_daily_time_limiter = DailyNumberLimiter(PGET_DAILY_LIMIT)

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
[pixiv群设置] 查看当前群的设置
[pixiv获取插画|pget 作品ID/作品URL] 通过作品ID或URL获取指定作品
""".strip()

# 创建服务
sv = Service('pixiv-subscription', help_=HELP_TEXT, enable_on_default=True)


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
                'blocked_tags': []
            }

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
        if group_id in self.subscriptions:
            return self.subscriptions[group_id]
        return {
            'artists': [],
            'r18_enabled': False,
            'blocked_tags': []
        }

    def is_illust_allowed(self, illust: dict, group_id: str) -> bool:
        """检查作品是否允许在指定群推送"""
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

    @staticmethod
    async def download_image_as_base64(url: str) -> str:
        """下载图片并转换为base64编码"""
        try:
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            async with aiohttp.ClientSession(
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
            ) as session:
                async with session.get(url, proxy=PROXY_URL) as resp:
                    # 对图片数据进行处理，确保图相同数据不同，以防被屏蔽
                    if resp.status == 200:
                        image_data = await resp.read()
                        # 生成随机不重复数据（这里用作种子）
                        random.seed(str(uuid.uuid4()))  # 确保不重复
                        
                        # 使用 PIL 修改像素
                        img_buffer = io.BytesIO(image_data)
                        img = Image.open(img_buffer)
                        pixels = img.load()
                        width, height = img.size
                        # 随机修改右下角像素（例如改变红色通道 +1）
                        x, y = random.randint(0, width-1), random.randint(0, height-1)
                        r, g, b = pixels[x, y][:3]  # 假设 RGB
                        pixels[x, y] = (r + 1 % 256, g, b)  # 微调
                        
                        # 保存回缓冲区
                        output_buffer = io.BytesIO()
                        img.save(output_buffer, format=img.format)
                        modified_data = output_buffer.getvalue()
                        
                        b64_data = base64.b64encode(modified_data).decode('utf-8')
                        return b64_data
                    else:
                        sv.logger.error(f"下载图片失败, HTTP {resp.status}: {url}")

        except Exception as e:
            sv.logger.error(f"下载图片异常: {e}, URL: {url}")

        return ""

    @staticmethod
    def get_image_urls(illust: dict) -> str:
        """获取作品的所有图片URL（正确处理单页和多页）"""
        urls = []
        
        page_count = illust.get('page_count', 1)
        
        if page_count > 1:
            # 多页作品：从 meta_pages 中提取每个页面的 original URL
            meta_pages = illust.get('meta_pages', [])
            for page in meta_pages:
                image_urls = page.get('image_urls', {})
                original_url = image_urls.get('original')  # 或 'large' / 'medium'
                if not original_url:
                    original_url = image_urls.get('large')
                if original_url:
                    urls.append(original_url)
        else:
            # 单页作品：从 meta_single_page 中提取 original_image_url
            meta_single_page = illust.get('meta_single_page', {})
            original_url = meta_single_page.get('original_image_url')
            if original_url:
                urls.append(original_url)
        
        if not urls:
            sv.logger.error(f"未找到任何图片URL for illust {illust.get('id')}. Illust data: {illust}")  # 添加调试日志
        
        return urls  # 返回列表，即使单张也是 [url]
        
    # 新方法：下载Ugoira并合成GIF base64
    async def download_ugoira_as_gif_base64(self, illust) -> str:
        """下载Ugoira ZIP，合成GIF，转为base64"""
        MAX_FRAMES = 600  # 限制最大帧数，防止GIF过大
        illust_id = illust.get('id')
        if not illust_id:
            sv.logger.error("未找到 illust_id")
            return ""
        
        try:
            # 调用 Pixiv API 获取 Ugoira 元数据（同步调用，无 await）
            metadata = self.api.ugoira_metadata(illust_id)
            if not metadata or 'ugoira_metadata' not in metadata:
                sv.logger.error(f"获取 Ugoira 元数据失败 for illust {illust_id}")
                return ""
            
            zip_urls = metadata['ugoira_metadata'].get('zip_urls', {})
            zip_url = zip_urls.get('medium') # 优先 medium 分辨率（较小），或 original
            if not zip_url or not zip_url.endswith('.zip'):
                sv.logger.error(f"无效的 Ugoira ZIP URL: {zip_url}")
                # 回退：下载第一帧作为静态图片
                fallback_url = illust.get('meta_single_page', {}).get('original_image_url')
                if fallback_url:
                    b64_data = await self.download_image_as_base64(fallback_url)  # 使用现有下载方法
                    return b64_data if b64_data else ""
                return ""
            
            # 下载 ZIP
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.get(zip_url, proxy=PROXY_URL) as resp:
                    if resp.status != 200:
                        sv.logger.error(f"下载Ugoira ZIP失败, HTTP {resp.status}: {zip_url}")
                        return ""
                    
                    zip_data = await resp.read()
                    with io.BytesIO(zip_data) as zip_buffer:
                        with zipfile.ZipFile(zip_buffer) as zip_file:
                            # 提取元数据（延迟）从 API 返回中取
                            frames_info = metadata['ugoira_metadata'].get('frames', [])[:MAX_FRAMES]
                            
                            # 提取帧
                            images = []
                            durations = []
                            frame_files = sorted([f for f in zip_file.namelist() if f.endswith(('.jpg', '.png'))])[:MAX_FRAMES]
                            for i, frame in enumerate(frame_files):
                                with zip_file.open(frame) as frame_file:
                                    img = Image.open(io.BytesIO(frame_file.read()))
                                    images.append(img)
                                durations.append(frames_info[i]['delay'] if i < len(frames_info) else 100)  # 默认100ms
                            
                            if not images:
                                sv.logger.error("未提取到Ugoira帧")
                                return ""
                            
                            # 对gif轻微修改像素（确保字节流不重复），以防屏蔽
                            try:
                                # 生成随机不重复种子（使用 UUID）
                                random.seed(str(uuid.uuid4()))
                                
                                # 随机选择一帧进行修改
                                frame_to_modify = random.randint(0, len(images) - 1)
                                img_to_modify = images[frame_to_modify]
                                
                                # 获取像素访问器
                                pixels = img_to_modify.load()
                                width, height = img_to_modify.size
                                
                                # 随机选择一个像素位置（优先边缘）
                                x = random.randint(0, width - 1)
                                y = random.randint(0, height - 1)
                                
                                # 假设 RGB/RGBA 模式，微调一个通道（例如红色 +1，循环到 0-255）
                                if img_to_modify.mode in ('RGB', 'RGBA'):
                                    r, g, b = pixels[x, y][:3]
                                    pixels[x, y] = ((r + 1) % 256, g, b) + pixels[x, y][3:]  # 保持 alpha 如果有
                                elif img_to_modify.mode == 'P':  # 调色板模式，微调索引
                                    pixel_value = pixels[x, y]
                                    pixels[x, y] = (pixel_value + 1) % 256
                                else:
                                    # 其他模式：跳过修改
                                    sv.logger.warning(f"跳过像素修改：不支持的图像模式 {img_to_modify.mode}")
                                    pass
                                
                                # 更新回列表
                                images[frame_to_modify] = img_to_modify
                                
                                sv.logger.info(f"已修改帧 {frame_to_modify} 的像素 ({x}, {y}) 以确保字节流唯一")
                            except Exception as e:
                                sv.logger.error(f"像素修改失败: {e}，使用原始帧")
                                # 回退：不修改，继续使用原始 images
                            
                            # 合成GIF（无限循环）
                            gif_buffer = io.BytesIO()
                            images[0].save(gif_buffer, format='GIF', save_all=True, append_images=images[1:], duration=durations, loop=0)
                            gif_bytes = gif_buffer.getvalue()
                            if len(gif_bytes) > 20 * 1024 * 1024:  # 大于20MB则回退到第一帧
                                sv.logger.warning("GIF太大，无法发送")
                                first_frame_bytes = io.BytesIO()
                                images[0].save(first_frame_bytes, format='JPEG')
                                return base64.b64encode(first_frame_bytes.getvalue()).decode('utf-8')
                            
                            return base64.b64encode(gif_bytes).decode('utf-8')
        except zipfile.BadZipFile as e:
            sv.logger.error(f"ZIP文件无效: {e}, URL: {zip_url}")
            return ""  # 或回退到静态
        except Exception as e:
            sv.logger.error(f"处理Ugoira异常: {e}, illust_id: {illust_id}")
            return ""
    
    
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

    blocked_tags = settings['blocked_tags']
    if blocked_tags:
        msg += f"🚫 屏蔽tag: {', '.join(blocked_tags)}"
    else:
        msg += "🚫 屏蔽tag: 无"

    await bot.send(ev, msg)

#更新支持多图输出和动图输出，图片数量多于20则分批发送，保证每次消息的图片数量最多为20
@sv.on_prefix('pixiv获取插画', 'pget')
async def fetch_illust(bot, ev: CQEvent):
    """根据作品ID获取插画，支持分开发送多张图片（每条消息最多20张）"""
    if not pget_daily_time_limiter.check(ev.user_id):
        return await bot.send(ev, f"❌ 获取插画的次数已达上限")

    input_text = ev.message.extract_plain_text().strip()
    if not input_text:
        return await bot.send(ev, "请输入作品ID或作品链接")

    # 尝试从URL中提取ID
    match = re.search(r'/artworks/(\d+)', input_text)
    if match:
        illust_id = match.group(1)
    else:
        illust_id = input_text

    if not illust_id.isdigit():
        return await bot.send(ev, "无效的作品ID或链接")

    # 获取 illust 数据
    illust = await manager.get_illust_by_id(illust_id)
    if not illust:
        return await bot.send(ev, f"作品ID {illust_id} 被吞掉啦~")

    # 提取信息
    title = illust.get('title', '无标题')
    user_info = illust.get('user')
    artist_name = user_info['name'] if user_info else f"作品ID {illust_id}"
    tags = illust.get('tags', [])

    # 构建消息列表
    MAX_IMAGES_PER_MESSAGE = 20  # 每条消息的最大图片数，qq每次消息的图片数量上限，请勿大于20
    messages = []  # 最终消息列表
    current_msg_parts = [f"🎨 {title}", f"🖌️ {artist_name}", f"🏷️ {', '.join([tag.get('name', '') for tag in tags[:3] if tag.get('name')])}"]
    image_count = 0  # 当前消息的图片计数
    part_index = 1   # 消息分页索引

    illust_type = illust.get('type', 'illust')

    if illust_type == 'ugoira':
        b64_gif = await manager.download_ugoira_as_gif_base64(illust)
        if b64_gif:
            current_msg_parts.append(f"\n[CQ:image,file=base64://{b64_gif}]")  # 发送GIF，计为1张
            image_count += 1
        else:
            current_msg_parts.append("\n❌ 无法合成Ugoira动图")
    else:
        # 原有静态图片逻辑
        image_urls = manager.get_image_urls(illust)
        if not image_urls:
            current_msg_parts.append("\n❌ 未找到图片URL")
        else:
            downloaded_images = []
            for url in image_urls:
                b64_data = await manager.download_image_as_base64(url)
                if b64_data:
                    # 检查是否需要分割消息
                    if image_count >= MAX_IMAGES_PER_MESSAGE:
                        # 当前消息已满，添加分页提示并保存
                        if part_index > 1:
                            current_msg_parts.append(f"\n（第 {part_index} 部分，继续查看下一条消息）")
                        messages.append('\n'.join(current_msg_parts))
                        part_index += 1
                        # 重置当前消息，添加续上下文
                        current_msg_parts = [f"🎨 {title}（续）", f"🖌️ {artist_name}"]
                        image_count = 0

                    current_msg_parts.append(f"\n[CQ:image,file=base64://{b64_data}]")
                    image_count += 1
                else:
                    sv.logger.error(f"图片下载失败: {url}")
                    current_msg_parts.append("\n❌ 图片下载失败")

    # 添加最后一条消息（如果有内容）
    if current_msg_parts:
        if part_index > 1:
            current_msg_parts.append(f"\n（第 {part_index} 部分，结束）")
        messages.append('\n'.join(current_msg_parts))

    # 如果没有成功构建任何消息，返回错误
    if not messages:
        return await bot.send(ev, "❌ 所有图片下载失败")

    # 循环发送消息
    for msg in messages:
        await bot.send(ev, msg, timeout=60)
        await asyncio.sleep(1)  # 延迟1秒，避免风控

    # 只在成功发送后增加计数
    pget_daily_time_limiter.increase(ev.user_id)
    return await bot.send(ev, '\n'.join(msg_parts), timeout=60)


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

#更新支持多图输出和动图输出，图片数量多于20则分批发送，保证每次消息的图片数量最多为20
async def construct_group_message(bot, group_id: int, artist_name: str, filtered_illusts: List[Dict]) -> str:
    """
    构建并分条发送群消息。如果图片总数超过限制，会自动分割成多条消息。
    函数会自己处理发送逻辑，并返回一个空字符串以防止上层重复发送。
    """
    MAX_IMAGES_PER_MESSAGE = 20  # 每条消息的最大图片数
    MAX_IMAGES_PER_ILLUST = 20   # 每个作品最多显示的图片数（防止单个作品图片过多）

    messages_to_send = []        # 最终要发送的消息列表
    current_msg_parts = []       # 当前正在构建的消息部分
    image_count_in_current_msg = 0 # 当前消息中的图片计数
    part_index = 1               # 分页索引

    # 初始化第一条消息的头部
    header = f"🎨 {artist_name} 有新作品更新！"
    current_msg_parts.append(header)

    total_illusts_to_show = filtered_illusts[:MAX_DISPLAY_WORKS]

    for i, illust in enumerate(total_illusts_to_show):
        title = illust.get('title', '无标题')
        tags = [tag.get('name', '') for tag in illust.get('tags', [])[:3] if tag.get('name')]
        
        illust_info_parts = [f"\n\n📖 {title}"]
        if tags:
            illust_info_parts.append(f"\n🏷️ {', '.join(tags)}")

        illust_type = illust.get('type', 'illust')

        # 预先获取图片URL或处理动图
        image_b64_list = []
        is_ugoira_failed = False
        
        if illust_type == 'ugoira':
            b64_gif = await manager.download_ugoira_as_gif_base64(illust)
            if b64_gif:
                image_b64_list.append(b64_gif)
            else:
                is_ugoira_failed = True
        else:
            image_urls = manager.get_image_urls(illust)
            if image_urls:
                # 限制单个作品的图片数量
                urls_to_download = image_urls[:MAX_IMAGES_PER_ILLUST]
                if len(image_urls) > MAX_IMAGES_PER_ILLUST:
                    illust_info_parts.append(f"\n（作品共 {len(image_urls)} 张图，仅显示前 {MAX_IMAGES_PER_ILLUST} 张）")

                for url in urls_to_download:
                    b64_data = await manager.download_image_as_base64(url)
                    if b64_data:
                        image_b64_list.append(b64_data)

        # 检查在添加此作品前是否需要分割消息
        # 如果当前消息加上新作品的图片会超限，则先发送当前消息
        if image_count_in_current_msg > 0 and (image_count_in_current_msg + len(image_b64_list)) > MAX_IMAGES_PER_MESSAGE:
            if part_index > 0: # part_index从1开始，所以总是>0
                 current_msg_parts.append(f"\n\n（第 {part_index} 部分，请继续查收）")
            messages_to_send.append(''.join(current_msg_parts))
            part_index += 1
            # 重置下一条消息
            current_msg_parts = [f"{header} (续)"]
            image_count_in_current_msg = 0

        # 将作品信息添加到当前消息
        current_msg_parts.extend(illust_info_parts)
        
        # 处理图片和错误信息
        if is_ugoira_failed:
            current_msg_parts.append("\n❌ 无法合成Ugoira动图")
        
        if not image_b64_list and illust_type != 'ugoira':
             current_msg_parts.append("\n❌ 图片下载失败或未找到URL")
        else:
            for b64_data in image_b64_list:
                # 在添加每张图片前再次检查是否需要分割（应对单个作品图片超多的情况）
                if image_count_in_current_msg >= MAX_IMAGES_PER_MESSAGE:
                    if part_index > 0:
                        current_msg_parts.append(f"\n\n（第 {part_index} 部分，请继续查收）")
                    messages_to_send.append(''.join(current_msg_parts))
                    part_index += 1
                    current_msg_parts = [f"{header} (续)"]
                    image_count_in_current_msg = 0

                current_msg_parts.append(f"\n[CQ:image,file=base64://{b64_data}]")
                image_count_in_current_msg += 1

    # 添加末尾提示
    if len(filtered_illusts) > MAX_DISPLAY_WORKS:
        current_msg_parts.append(f"\n\n...还有 {len(filtered_illusts) - MAX_DISPLAY_WORKS} 个新作品未展示。")

    # 将最后构建的消息添加到待发送列表
    if current_msg_parts:
        if part_index > 1:
            current_msg_parts.append(f"\n\n（第 {part_index} 部分，结束）")
        messages_to_send.append(''.join(current_msg_parts))

    for msg in messages_to_send:
        try:
            await bot.send_group_msg(group_id=group_id, message=msg, timeout=120) # 增加超时
            await asyncio.sleep(1)  # 避免风控
        except Exception as e:
            sv.logger.error(f"向群 {group_id} 发送分片消息失败: {e}")

    # 返回空字符串，防止上层代码重复发送
    return ""

#调整更新发送方式以适应多图分割发送
@sv.scheduled_job('interval', hours=CHECK_INTERVAL_HOURS)
async def check_updates():
    start_time = datetime.now()

    bot = nonebot.get_bot()

    # 计算本次检查的时间窗口 - 以当前时间为结束点，向前检查CHECK_INTERVAL_HOURS的小时数
    check_time = datetime.now(timezone.utc)

    # 收集所有需要检查的画师ID，并记录哪些群订阅了哪些画师
    artist_to_groups = {}  # {artist_id: [group_id1, group_id2, ...]}

    for group_id, group_data in manager.subscriptions.items():
        artists = group_data.get('artists', [])
        for user_id in artists:
            if user_id not in artist_to_groups:
                artist_to_groups[user_id] = []
            artist_to_groups[user_id].append(group_id)

    if not artist_to_groups:  # 没有订阅任何画师
        return

    # 对每个画师只请求一次
    for user_id, group_ids in artist_to_groups.items():
        try:
            # 使用精确的时间窗口获取新作品
            user_info, new_illusts = await manager.get_new_illusts_with_user_info(
                user_id,
                start_time=check_time,
                interval_hours=CHECK_INTERVAL_HOURS
            )

            artist_name = user_info['name'] if user_info else f"画师ID:{user_id}"

            # 如果没有新作品，跳过
            if not new_illusts:
                sv.logger.info(f"{artist_name} 没有新作品，跳过")
                await asyncio.sleep(3) # 避免频繁请求API
                continue

            # 向所有订阅了该画师的群组发送消息（根据群设置过滤内容）
            for group_id in group_ids:
                try:
                    # 根据群设置过滤作品
                    filtered_illusts = []
                    for illust in new_illusts:
                        is_allowed = manager.is_illust_allowed(illust, group_id)
                        if is_allowed:
                            filtered_illusts.append(illust)

                    # 如果过滤后没有作品，跳过这个群
                    if not filtered_illusts:
                        continue
                    
                    await construct_group_message(bot, int(group_id), artist_name, filtered_illusts)
                    
                    # 避免发送消息过快被限制
                    await asyncio.sleep(1)

                except Exception as e:
                    sv.logger.error(f"向群 {group_id} 发送画师 {user_id} 更新消息时出错: {e}")
                    continue

            # 避免频繁请求API
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
