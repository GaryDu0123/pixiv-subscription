#!/usr/bin/env python
# -*-coding:utf-8 -*-
import asyncio
import re

from hoshino import Service, priv
from hoshino.typing import CQEvent
from .pixiv import manager
from hoshino.config import NICKNAME
from .utils import send_messages
from hoshino.util import DailyNumberLimiter, FreqLimiter
from .config import MAX_DISPLAY_WORKS
try:
    from .config import CHAIN_REPLY, RANK_LIMIT, PGET_DAILY_LIMIT, PREVIEW_ILLUSTRATOR_LIMIT, RANK_CD_MINUTES
except ImportError:
    CHAIN_REPLY = True  # 默认启用合并转发回复模式
    RANK_LIMIT = 5     # 默认展示排行榜作品数量为5
    PGET_DAILY_LIMIT = 10  # 兼容旧配置
    PREVIEW_ILLUSTRATOR_LIMIT = 10
    RANK_CD_MINUTES = 60

limiter = FreqLimiter(RANK_CD_MINUTES)  # 每60秒限制一次请求
pget_daily_time_limiter = DailyNumberLimiter(PGET_DAILY_LIMIT)
preview_illustrator_limiter = DailyNumberLimiter(PREVIEW_ILLUSTRATOR_LIMIT)

if isinstance(NICKNAME, str):
    NICKNAME = [NICKNAME]

HELP = '''
[pixiv预览画师 画师ID/画师URL] 预览画师最新作品
[pixiv获取插画|pget 作品ID/作品URL] 通过作品ID或URL获取指定作品
[pixiv日榜] 获取插画日榜
[pixiv男性向排行] 获取插画男性向排行榜
[pixiv女性向排行] 获取插画女性向排行榜
[pixiv周榜] 获取插画周榜
[pixiv月榜] 获取插画月榜
[pixiv原画榜] 获取插画原画榜
'''.strip()

sv = Service(
    'pixiv-tools',
    help_=HELP,
    enable_on_default=False
)


async def send_ranking(bot, ev: CQEvent, mode: str, title: str):
    """
    Sends ranking images, gets ranking data for the specified mode,
    and uses the send_messages function to send them.
    """
    group_id = str(ev.group_id)
    if not limiter.check(group_id):
        limiter.left_time(group_id)
        await bot.finish(ev, f"Pixiv排行榜请求过于频繁，请稍后再试~")
        return
    limiter.start_cd(group_id)
    await bot.send(ev, f"正在获取Pixiv{title}，请稍候...")

    # 获取排行榜数据
    illusts = await manager.get_ranking(mode=mode)

    if not illusts:
        await bot.send(ev, f"获取{title}失败，可能是Pixiv API暂时无法访问或当前榜单无内容。")
        return

    await asyncio.sleep(1)

    # 准备要发送的消息列表
    messages_to_send = []
    for i, illust in enumerate(illusts[:RANK_LIMIT]):
        rank = i + 1
        illust_title = illust.get('title', '无标题')
        artist_name = illust.get('user', {}).get('name', '未知画师')

        msg_parts = [
            f"Top {rank}",
            f"🎨 作品: {illust_title}",
            f"🖌️ 画师: {artist_name}",
        ]

        # 下载图片并转换为Base64
        image_url = manager.get_image_urls(illust)
        if image_url:
            b64_data = await manager.download_image_as_base64(image_url)
            if b64_data:
                msg_parts.append(f"[CQ:image,file=base64://{b64_data}]")
            else:
                msg_parts.append("(图片下载失败)")
        else:
            msg_parts.append("(未找到图片URL)")

        messages_to_send.append('\n'.join(msg_parts))

    await send_messages(bot, ev, messages_to_send)


@sv.on_prefix('pixiv预览画师')
async def get_artist_illusts(bot, ev: CQEvent):
    """
    获取指定画师的最新作品, 增加了群聊发送规则判断.
    """
    if not preview_illustrator_limiter.check(ev.user_id):
        return await bot.send(ev, f"❌ 今日预览画师作品的次数已达上限")

    input_text = ev.message.extract_plain_text().strip()
    if not input_text:
        return await bot.send(ev, "请输入画师ID或用户主页链接")

    # 尝试从URL中提取ID
    match = re.search(r'/users/(\d+)', input_text)
    if match:
        artist_id = match.group(1)
    else:
        artist_id = input_text

    if not artist_id.isdigit():
        return await bot.send(ev, "无效的画师ID或链接")

    await bot.send(ev, f"正在获取画师 {artist_id} 的最新作品...")

    # 获取画师所有近期作品, api限制默认获取前30个作品
    illusts, user_info = await manager.user_illusts(artist_id)
    if not illusts:
        return await bot.send(ev, f"获取画师 {artist_id} 的作品失败，可能是画师ID不存在、该画师没有作品或API暂时无法访问。")

    # 筛选允许发送的作品
    allowed_illusts = []
    group_id = ev.group_id

    for illust in illusts:
        # 判断该作品是否允许在本群发送
        if manager.is_illust_allowed(illust, group_id):
            allowed_illusts.append(illust)
            # 如果已达到最大显示数量，则停止筛选
            if len(allowed_illusts) >= MAX_DISPLAY_WORKS:
                break

    # 判断是否有可发送的作品
    if not allowed_illusts:
        return await bot.send(ev, f"画师 {artist_id} 的近期作品不符合本群的设置~")

    # 给消息分块准备内容
    messages_to_send = []
    if user_info:
        info = [
            f"画师: {user_info.get('name', '未知')} (ID: {artist_id})"
        ]
        if user_info.get('profile_image_urls') and user_info['profile_image_urls'].get('medium'):
            profile_image = await manager.download_image_as_base64(user_info['profile_image_urls']['medium'])
            info.append(f"[CQ:image,file=base64://{profile_image}]")
        messages_to_send.append('\n'.join(info))

    for illust in allowed_illusts:
        illust_title = illust.get('title', '无标题')
        tags = [tag.get('name', '') for tag in illust.get('tags', [])[:3] if tag.get('name')]

        msg_parts = [
            f"📖 {illust_title}",
        ]
        if tags:
            msg_parts.append(f"🏷️ {', '.join(tags)}")

        image_url = manager.get_image_urls(illust)
        if image_url:
            b64_data = await manager.download_image_as_base64(image_url)
            if b64_data:
                msg_parts.append(f"[CQ:image,file=base64://{b64_data}]")
            else:
                msg_parts.append("(图片下载失败)")
        else:
            msg_parts.append("(未找到图片URL)")

        messages_to_send.append('\n'.join(msg_parts))

    # 发送消息
    await send_messages(bot, ev, messages_to_send)
    preview_illustrator_limiter.increase(ev.user_id)
    return None


@sv.on_fullmatch('pixiv日榜')
async def daily_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day', title='插画日榜')

@sv.on_fullmatch('pixiv男性向排行')
async def male_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day_male', title='男性向排行榜')

@sv.on_fullmatch('pixiv女性向排行')
async def female_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day_female', title='女性向排行榜')

@sv.on_fullmatch('pixiv周榜')
async def weekly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='week', title='插画周榜')


@sv.on_fullmatch('pixiv月榜')
async def monthly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='month', title='插画月榜')

@sv.on_fullmatch('pixiv原画榜')
async def original_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='week_original', title='原画榜')


@sv.on_prefix('pixiv获取插画', 'pget')
async def fetch_illust(bot, ev: CQEvent):
    """
    根据作品ID获取插画。
    - 支持动图(ugoira)。
    - 当作品图片超过3张时，自动转为合并转发。
    """
    if not pget_daily_time_limiter.check(ev.user_id):
        return await bot.send(ev, "❌ 获取插画的次数已达今日上限")

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

    illust = await manager.get_illust_by_id(illust_id)
    if not illust:
        return await bot.send(ev, f"作品ID {illust_id} 被吞掉啦~")

    # 检查作品是否允许在本群发送
    if not manager.is_illust_allowed(illust, ev.group_id):
        return await bot.send(ev, "❌ 该作品不符合本群的设置，无法发送~")

    # 构建基础文本消息
    title = illust.get('title', '无标题')
    artist_name = illust.get('user', {}).get('name', '未知画师')
    tags = [tag.get('name', '') for tag in illust.get('tags', [])[:5] if tag.get('name')]
    text_message = (
        f"🎨 {title}\n"
        f"🖌️ {artist_name}\n"
        f"🏷️ {', '.join(tags)}"
    )

    illust_type = illust.get('type')

    # 处理动图
    if illust_type == 'ugoira':
        b64_data = await manager.download_ugoira_as_gif_base64(illust)
        if b64_data:
            final_message = f"{text_message}\n[CQ:image,file=base64://{b64_data}]"
            await bot.send(ev, final_message)
        else:
            await bot.send(ev, f"{text_message}\n(动图处理失败)")

    # 处理静态图
    elif illust_type == 'illust':
        image_urls = manager.get_image_urls(illust)
        if not image_urls:
            return await bot.send(ev, f"{text_message}\n(未找到任何图片URL)")

        page_count = len(image_urls)

        # 如果图片过多，则使用合并转发
        if page_count > 3:
            messages_to_forward = [text_message]
            for url in image_urls[:MAX_DISPLAY_WORKS]:
                b64_data = await manager.download_image_as_base64(url)
                if b64_data:
                    messages_to_forward.append(f"[CQ:image,file=base64://{b64_data}]")

            if len(image_urls) > MAX_DISPLAY_WORKS:
                messages_to_forward.append(f"该作品共有 {len(image_urls)} 张图片，仅展示前 {MAX_DISPLAY_WORKS} 张。")

            await send_messages(bot, ev, messages_to_forward)

        # 否则，合并为一条消息发送
        else:
            message_parts = []
            for url in image_urls:
                b64_data = await manager.download_image_as_base64(url)
                if b64_data:
                    message_parts.append(f"[CQ:image,file=base64://{b64_data}]")

            final_message = '\n'.join(message_parts)
            await bot.send(ev, final_message)
    pget_daily_time_limiter.increase(ev.user_id)
    return None