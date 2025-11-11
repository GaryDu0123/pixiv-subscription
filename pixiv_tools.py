#!/usr/bin/env python
# -*-coding:utf-8 -*-
import asyncio
from hoshino import Service
from hoshino.typing import CQEvent
from .pixiv import manager
from hoshino.config import NICKNAME
try:
    from .config import CHAIN_REPLY, RANK_LIMIT
except ImportError:
    CHAIN_REPLY = True  # 默认使用合并转发
    RANK_LIMIT = 15     # 默认显示15张

if type(NICKNAME) == str:
    NICKNAME = [NICKNAME]

HELP = '''
🎨 Pixiv查询插件
[插画搜索 关键词] 搜索相关作品
[插画画师 画师ID] 获取画师最新作品
[插画相关 作品ID] 获取相关推荐作品
[插画日榜] 获取Pixiv插画日榜
[插画男性向排行] 获取Pixiv插画男性向排行榜
[插画女性向排行] 获取Pixiv插画女性向排行榜
[插画周榜] 获取Pixiv插画周榜
[插画月榜] 获取Pixiv插画月榜
[插画原画榜] 获取Pixiv插画原画榜
'''.strip()

sv = Service(
    'pixiv-tools',
    help_=HELP,
    enable_on_default=False
)


async def send_ranking(bot, ev: CQEvent, mode: str, title: str):
    """
    发送排行榜图片, 获取指定模式的排行榜数据, 根据 CHAIN_REPLY 配置决定发送方式（合并转发或逐条发送）, 限制发送数量为 RANK_LIMIT。
    """
    await bot.send(ev, f"正在获取Pixiv{title}，请稍候...")

    # 从 manager 获取排行榜数据
    illusts = await manager.get_ranking(mode=mode)

    # 检查获取结果
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

    if CHAIN_REPLY:
        # 合并转发模式
        forward_nodes = [
            {
                "type": "node",
                "data": {
                    "name": str(NICKNAME[0]),
                    "user_id": str(ev.self_id),
                    "content": str(msg)
                }
            }
            for msg in messages_to_send
        ]
        await bot.send_group_forward_msg(group_id=ev.group_id, messages=forward_nodes)
    else:
        # 逐条发送模式
        for msg in messages_to_send:
            await bot.send(ev, msg)
            # 增加延迟，避免消息发送过快被风控
            await asyncio.sleep(2)

@sv.on_fullmatch('插画日榜')
async def daily_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day', title='插画日榜')

@sv.on_fullmatch('插画男性向排行')
async def monthly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day_male', title='男性向排行榜')

@sv.on_fullmatch('插画女性向排行')
async def monthly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='day_female', title='女性向排行榜')

@sv.on_fullmatch('插画周榜')
async def weekly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='week', title='插画周榜')


@sv.on_fullmatch('插画月榜')
async def monthly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='month', title='插画月榜')


@sv.on_fullmatch('插画原画榜')
async def monthly_ranking(bot, ev: CQEvent):
    await send_ranking(bot, ev, mode='week_original', title='原画榜')