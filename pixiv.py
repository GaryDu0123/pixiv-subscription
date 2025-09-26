import base64
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
import nonebot
from hoshino import Service, priv
from hoshino.typing import CQEvent
from pixivpy3 import AppPixivAPI
from .config import PROXY_URL, MAX_DISPLAY_WORKS, IMAGE_QUALITY, CHECK_INTERVAL_HOURS
import aiohttp

# 插件配置
PIXIV_REFRESH_TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'refresh-token.json')
PIXIV_SUBSCRIPTION_PATH = os.path.join(os.path.dirname(__file__), 'subscriptions.json')

if IMAGE_QUALITY not in ['large', 'medium', 'square_medium', 'original']:
    IMAGE_QUALITY = 'large'  # 默认值

HELP_TEXT = """
🎨 pixiv画师订阅插件
[pixiv订阅画师 画师ID] 订阅画师
[pixiv取消订阅 画师ID] 取消订阅画师  
[pixiv订阅列表] 查看订阅列表
[pixiv重设登录token] 设置refresh_token (管理员)
[pixiv开启r18] 允许推送R18内容 (管理员)
[pixiv关闭r18] 屏蔽R18内容 (管理员)
[pixiv屏蔽tag tag名] 屏蔽包含指定tag的作品 (管理员)
[pixiv取消屏蔽tag tag名] 取消屏蔽指定tag (管理员)
[pixiv群设置] 查看当前群的设置
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

            sv.logger.info(f"检查画师 {user_id} 时间范围: {check_start} 到 {check_end}")

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
                    timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.get(url, proxy=PROXY_URL) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        # 转换为base64
                        b64_data = base64.b64encode(image_data).decode('utf-8')
                        return b64_data
                    else:
                        sv.logger.error(f"下载图片失败, HTTP {resp.status}: {url}")

        except Exception as e:
            sv.logger.error(f"下载图片异常: {e}, URL: {url}")

        return ""

    @staticmethod
    def get_image_urls(illust: dict) -> str:
        """
        获取作品的图片URL, 无论是单图还是多图都是返回第一张图的URL
        todo 如果需要找原图, 需要去meta_pages里找
        """
        url = ""
        # 单独处理原图的请求
        if IMAGE_QUALITY == 'original':
            # 尝试获取原图
            # 单图会在meta_single_page里
            if not url and 'meta_single_page' in illust and illust['meta_single_page']:
                url = illust['meta_single_page'].get('original_image_url', "")
            # 多图会在meta_pages里
            if 'meta_pages' in illust and illust['meta_pages']:
                url = illust['meta_pages'][0]['image_urls'].get('original', "")
            if not url:
                # 回退到large
                url = illust['image_urls'].get('large', "")
            return url
        # 其他清晰度
        if 'image_urls' in illust:
            url = illust['image_urls'].get(IMAGE_QUALITY)
        return url

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
    user_id = ev.message.extract_plain_text().strip()
    if not user_id:
        await bot.send(ev, "请输入画师ID\n例：订阅画师 123456")
        return
    if not user_id.isdigit():
        await bot.send(ev, "画师ID必须为数字")
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
    user_id = ev.message.extract_plain_text().strip()
    if not user_id:
        await bot.send(ev, "请输入要取消订阅的画师ID\n例：取消订阅 123456")
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

    msg = "当前订阅的画师:\n"
    msg += "\n".join([f"{user_id}" for user_id in subscriptions])

    await bot.send(ev, msg)


@sv.on_prefix('pixiv重设登录token')
async def set_pixiv_token(bot, ev: CQEvent):
    """设置pixiv refresh_token (仅群主/管理员)"""
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "只有群主或管理员才能设置pixiv refresh_token")
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


async def construct_group_message(artist_name: str, filtered_illusts: List[Dict]) -> str:
    """
    构建发送到群的消息内容, 并限制最多显示MAX_DISPLAY_WORKS个作品
    其他作品会以"...还有 N 个新作品"的形式提示
    """
    # 构建消息
    msg_parts = [f"🎨 {artist_name} 有新作品更新！"]

    for i, illust in enumerate(filtered_illusts[:MAX_DISPLAY_WORKS]):  # 最多显示配置的作品数量
        title = illust.get('title', '无标题')

        # 获取标签
        tags = []
        if 'tags' in illust:
            tags = [tag.get('name', '') for tag in illust['tags'][:3] if tag.get('name')]

        msg_parts.append(f"\n📖 {title}")
        if tags:
            msg_parts.append(f"\n🏷️ {', '.join(tags)}")

        image_url = manager.get_image_urls(illust)
        if image_url:
            b64_data = await manager.download_image_as_base64(image_url)
            if b64_data:
                msg_parts.append(f"\n[CQ:image,file=base64://{b64_data}]")
            else:
                sv.logger.error(f"图片下载失败: {image_url}")

    if len(filtered_illusts) > MAX_DISPLAY_WORKS:
        msg_parts.append(f"\n...还有 {len(filtered_illusts) - MAX_DISPLAY_WORKS} 个新作品")

    return ''.join(msg_parts)


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

                    await bot.send_group_msg(
                        group_id=int(group_id),
                        message=await construct_group_message(artist_name, filtered_illusts)
                    )
                    # 避免发送消息过快被限制
                    await asyncio.sleep(1)

                except Exception as e:
                    sv.logger.error(f"向群 {group_id} 发送画师 {user_id} 更新消息时出错: {e}")
                    continue

            # 避免频繁请求API
            sv.logger.info(f"画师 {user_id} 处理完成，等待5秒...")
            await asyncio.sleep(3)
        except Exception as e:
            sv.logger.error(f"获取画师 {user_id} 更新时出错: {e}")
            import traceback
            sv.logger.error(f"错误堆栈: {traceback.format_exc()}")
            continue

    end_time = datetime.now()
    duration = end_time - start_time
    sv.logger.info(f"画师订阅检查完成，总耗时: {duration}, 结束时间: {end_time}")